//! The sidebar process: terminal, event loop, refresh threads, the click socket and the visibility signal.
//!
//! One thread owns the screen and every piece of state. The others only send it messages: the terminal's
//! events, the snapshot (every 2 seconds) and the run liveness and managed window (every 10 seconds), the
//! click socket's requests, and the tmux visibility. A frame is drawn once per batch of messages, and ratatui
//! writes only the cells that changed, so the screen never shows a state between two others.
use crate::data::Reader;
use crate::model::{Liveness, Snapshot};
use crate::tmuxio::{self, Tmux};
use crate::ui::{self, Action, Active, Facts, Hit, Interaction, Key, Layout};
use crossterm::event::{Event, KeyCode, KeyEventKind, KeyModifiers, MouseButton, MouseEventKind};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::Arc;
use std::time::{Duration, Instant};

const SNAPSHOT_EVERY: Duration = Duration::from_secs(2);
const LIVENESS_EVERY: Duration = Duration::from_secs(10);
/// Textual's `App.TOOLTIP_DELAY`.
const TOOLTIP_DELAY: Duration = Duration::from_millis(500);
/// A tooltip is hidden this long after the last mouse motion (docs/project-board-tui-plan.md section 3).
const TOOLTIP_IDLE: Duration = Duration::from_secs(5);
/// Textual's default notification timeout.
const TOAST_TIME: Duration = Duration::from_secs(5);
const CLICK_LIMIT: usize = 4096;

enum Msg {
    Snapshot(Snapshot, Option<Result<HashSet<String>, String>>),
    Live(Liveness, Option<Option<Active>>),
    Expanded(Result<HashSet<String>, String>),
    Input(Event),
    Click { client: String, x: i64, y: i64, reply: Sender<Value> },
    Visible(bool),
    Toast(String),
    Quit,
}

struct Config {
    config: Option<String>,
    click_socket: Option<String>,
}

struct App {
    config: Config,
    tx: Sender<Msg>,
    kicks: Vec<Sender<()>>,
    snapshot: Snapshot,
    live: Liveness,
    expanded: HashSet<String>,
    active: Option<Active>,
    notice: Option<String>,
    ui: Interaction,
    layout: Layout,
    size: (u16, u16),
    visible: bool,
    /// The first snapshot has arrived; before it the pane is empty rather than saying there is no project.
    loaded: bool,
    pointer: (u16, u16),
    tooltip_due: Option<(Instant, Key)>,
    tooltip: Option<String>,
    tooltip_expires: Option<Instant>,
    toast: Option<(String, Instant)>,
    mouse_down: Option<Key>,
    quit: bool,
}

pub fn run(config: Option<String>) -> i32 {
    let click_socket = std::env::var("PROJECT_BOARD_CLICK_SOCKET").ok().filter(|v| !v.is_empty());
    let (tx, rx) = mpsc::channel::<Msg>();
    let visible_flag = Arc::new(AtomicBool::new(true));
    let reader = Arc::new(Reader::new(config.as_deref().map(std::path::PathBuf::from)));
    let tmux = Arc::new(Tmux::from_env());

    // The handlers come before `mark_ready`: the default action of SIGUSR1 ends the process.
    watch_signals(tx.clone());

    let mut kicks = Vec::new();
    {
        let (kick_tx, kick_rx) = mpsc::channel::<()>();
        kicks.push(kick_tx);
        let (reader, tmux, tx, flag) = (reader.clone(), tmux.clone(), tx.clone(), visible_flag.clone());
        std::thread::spawn(move || snapshot_loop(reader, tmux, tx, flag, kick_rx));
    }
    {
        let (kick_tx, kick_rx) = mpsc::channel::<()>();
        kicks.push(kick_tx);
        let (reader, tmux, tx, flag) = (reader.clone(), tmux.clone(), tx.clone(), visible_flag.clone());
        std::thread::spawn(move || liveness_loop(reader, tmux, tx, flag, kick_rx));
    }
    {
        let (tmux, tx) = (tmux.clone(), tx.clone());
        std::thread::spawn(move || {
            let _ = tx.send(Msg::Visible(tmux.mark_ready()));
        });
    }
    let mut notice = None;
    if let Some(path) = &click_socket {
        notice = start_click_server(path, tx.clone());
    }

    let mut terminal = ratatui::init();
    let _ = crossterm::execute!(std::io::stdout(), crossterm::event::EnableMouseCapture, crossterm::event::EnableFocusChange);
    {
        let tx = tx.clone();
        std::thread::spawn(move || {
            while let Ok(event) = crossterm::event::read() {
                if tx.send(Msg::Input(event)).is_err() {
                    break;
                }
            }
        });
    }
    let size = terminal.size().map(|s| (s.width, s.height)).unwrap_or((25, 24));
    let mut app = App {
        config: Config { config, click_socket: click_socket.clone() },
        tx,
        kicks,
        snapshot: Snapshot::default(),
        live: Liveness::new(),
        expanded: HashSet::new(),
        active: None,
        notice,
        ui: Interaction::default(),
        layout: Layout::default(),
        size,
        visible: true,
        loaded: false,
        pointer: (0, 0),
        tooltip_due: None,
        tooltip: None,
        tooltip_expires: None,
        toast: None,
        mouse_down: None,
        quit: false,
    };
    let _ = app.draw(&mut terminal, false);
    while !app.quit {
        let message = match app.next_deadline() {
            Some(deadline) => match rx.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
                Ok(message) => Some(message),
                Err(RecvTimeoutError::Timeout) => None,
                Err(RecvTimeoutError::Disconnected) => break,
            },
            None => match rx.recv() {
                Ok(message) => Some(message),
                Err(_) => break,
            },
        };
        let mut dirty = app.expire();
        if let Some(message) = message {
            dirty |= app.handle(message, &visible_flag);
            while let Ok(message) = rx.try_recv() {
                dirty |= app.handle(message, &visible_flag);
            }
        }
        if dirty {
            let _ = app.draw(&mut terminal, true);
        }
    }
    let _ = crossterm::execute!(std::io::stdout(), crossterm::event::DisableFocusChange, crossterm::event::DisableMouseCapture);
    ratatui::restore();
    if let Some(path) = &click_socket {
        let _ = std::fs::remove_file(path);
    }
    0
}

fn watch_signals(tx: Sender<Msg>) {
    use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM, SIGUSR1};
    let Ok(mut signals) = signal_hook::iterator::Signals::new([SIGUSR1, SIGHUP, SIGINT, SIGTERM]) else { return };
    std::thread::spawn(move || {
        let tmux = Tmux::from_env();
        for signal in signals.forever() {
            let sent = if signal == SIGUSR1 { tx.send(Msg::Visible(tmux.visible())) } else { tx.send(Msg::Quit) };
            if sent.is_err() {
                break;
            }
        }
    });
}

/// Wait `every`, or less when kicked (a window that is shown again is read at once); returns false when the
/// process is going away.
fn pause(kick: &Receiver<()>, every: Duration) -> bool {
    match kick.recv_timeout(every) {
        Ok(()) | Err(RecvTimeoutError::Timeout) => true,
        Err(RecvTimeoutError::Disconnected) => false,
    }
}

fn now_seconds() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0)
}

fn snapshot_loop(reader: Arc<Reader>, tmux: Arc<Tmux>, tx: Sender<Msg>, visible: Arc<AtomicBool>, kick: Receiver<()>) {
    loop {
        let started = Instant::now();
        if visible.load(Ordering::Relaxed) {
            let snapshot = reader.snapshot(now_seconds());
            let (expanded, _) = tmux.refresh(false);
            if tx.send(Msg::Snapshot(snapshot, Some(expanded))).is_err() {
                return;
            }
        }
        if !pause(&kick, SNAPSHOT_EVERY.saturating_sub(started.elapsed())) {
            return;
        }
    }
}

fn liveness_loop(reader: Arc<Reader>, tmux: Arc<Tmux>, tx: Sender<Msg>, visible: Arc<AtomicBool>, kick: Receiver<()>) {
    loop {
        let started = Instant::now();
        if visible.load(Ordering::Relaxed) {
            let live = reader.liveness();
            let (_, context) = tmux.refresh(true);
            if tx.send(Msg::Live(live, context)).is_err() {
                return;
            }
        }
        if !pause(&kick, LIVENESS_EVERY.saturating_sub(started.elapsed())) {
            return;
        }
    }
}

/// Listen on the click socket (`PROJECT_BOARD_CLICK_SOCKET`). A path that is in use or cannot be opened is
/// reported on the first row, as the Python sidebar did. Returns that text.
fn start_click_server(path: &str, tx: Sender<Msg>) -> Option<String> {
    if std::fs::symlink_metadata(path).is_ok() {
        return Some("Board 클릭 socket 경로가 이미 사용 중입니다.".into());
    }
    let listener = match UnixListener::bind(path) {
        Ok(listener) => listener,
        Err(error) => return Some(format!("Board 클릭 socket 오류: {error}")),
    };
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
    }
    std::thread::spawn(move || {
        for stream in listener.incoming() {
            let Ok(stream) = stream else { continue };
            let tx = tx.clone();
            std::thread::spawn(move || serve_click(stream, tx));
        }
    });
    None
}

fn click_error(code: &str, message: &str) -> Value {
    json!({"ok": false, "data": null, "error": {"code": code, "message": message}})
}

fn serve_click(stream: UnixStream, tx: Sender<Msg>) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let mut line = Vec::new();
    let read = BufReader::new(&stream).take_line(&mut line, CLICK_LIMIT + 1);
    let reply = match read {
        Err(error) => click_error("invalid_click", &error.to_string()),
        Ok(_) if line.len() > CLICK_LIMIT => click_error("invalid_click", "click message too large"),
        Ok(_) => match serde_json::from_slice::<Value>(&line) {
            Err(error) => click_error("invalid_click", &error.to_string()),
            Ok(message) => dispatch_request(&message, &tx),
        },
    };
    let mut stream = stream;
    let _ = stream.write_all(format!("{reply}\n").as_bytes());
}

trait TakeLine {
    fn take_line(&mut self, into: &mut Vec<u8>, limit: usize) -> std::io::Result<usize>;
}
impl<R: BufRead> TakeLine for R {
    fn take_line(&mut self, into: &mut Vec<u8>, limit: usize) -> std::io::Result<usize> {
        let mut total = 0;
        loop {
            let available = self.fill_buf()?;
            if available.is_empty() {
                return Ok(total);
            }
            let (used, done) = match available.iter().position(|b| *b == b'\n') {
                Some(i) => (i + 1, true),
                None => (available.len(), false),
            };
            into.extend_from_slice(&available[..used]);
            self.consume(used);
            total += used;
            if done || total >= limit {
                return Ok(total);
            }
        }
    }
}

fn dispatch_request(message: &Value, tx: &Sender<Msg>) -> Value {
    let client = message.get("client").and_then(Value::as_str).filter(|c| !c.is_empty());
    let Some(client) = client else { return click_error("invalid_click", "client is required") };
    let coordinate = |name: &str| message.get(name).and_then(Value::as_i64).filter(|v| *v >= 0 && message[name].is_i64() || message[name].is_u64());
    let (Some(x), Some(y)) = (coordinate("x"), coordinate("y")) else {
        return click_error("invalid_click", "x and y must be nonnegative integers");
    };
    let (reply, answer) = mpsc::channel();
    if tx.send(Msg::Click { client: client.to_string(), x, y, reply }).is_err() {
        return click_error("click_unavailable", "the Board sidebar is closing");
    }
    answer.recv_timeout(Duration::from_secs(5)).unwrap_or_else(|_| click_error("click_unavailable", "the Board sidebar did not answer"))
}

impl App {
    fn next_deadline(&self) -> Option<Instant> {
        [self.tooltip_due.as_ref().map(|d| d.0), self.tooltip_expires, self.toast.as_ref().map(|t| t.1)].into_iter().flatten().min()
    }

    /// Timers that ran out; true when the screen changes.
    fn expire(&mut self) -> bool {
        let now = Instant::now();
        let mut dirty = false;
        if let Some((due, key)) = self.tooltip_due.clone() {
            if due <= now {
                self.tooltip_due = None;
                if self.ui.hover.as_ref() == Some(&key) {
                    self.tooltip = self.layout.widgets.iter().find(|w| w.key == key).and_then(|w| w.tooltip.clone());
                    dirty = self.tooltip.is_some();
                }
            }
        }
        if self.tooltip_expires.map_or(false, |t| t <= now) {
            self.tooltip_expires = None;
            dirty |= self.hide_tooltip();
        }
        if self.toast.as_ref().map_or(false, |t| t.1 <= now) {
            self.toast = None;
            dirty = true;
        }
        dirty
    }

    fn hide_tooltip(&mut self) -> bool {
        self.tooltip_due = None;
        self.tooltip.take().is_some()
    }

    fn handle(&mut self, message: Msg, visible_flag: &AtomicBool) -> bool {
        match message {
            Msg::Snapshot(snapshot, expanded) => {
                // A read that was under way when the window was hidden still shows (as the Python sidebar did).
                self.loaded = true;
                self.snapshot = snapshot;
                if let Some(Ok(expanded)) = expanded {
                    self.expanded = expanded;
                }
                true
            }
            Msg::Live(live, context) => {
                self.live = live;
                if let Some(active) = context {
                    self.active = active;
                }
                true
            }
            Msg::Expanded(Ok(expanded)) => {
                self.expanded = expanded;
                true
            }
            Msg::Expanded(Err(error)) => {
                self.toast = Some((error, Instant::now() + TOAST_TIME));
                true
            }
            Msg::Visible(visible) => {
                visible_flag.store(visible, Ordering::Relaxed);
                let shown = visible && !self.visible;
                self.visible = visible;
                if shown {
                    for kick in &self.kicks {
                        let _ = kick.send(());
                    }
                }
                false
            }
            Msg::Toast(text) => {
                self.toast = Some((text, Instant::now() + TOAST_TIME));
                true
            }
            Msg::Quit => {
                self.quit = true;
                false
            }
            Msg::Click { client, x, y, reply } => {
                let answer = self.dispatch_client_click(&client, x, y);
                let _ = reply.send(answer);
                true
            }
            Msg::Input(event) => self.input(event),
        }
    }

    fn facts_layout(&mut self) {
        let facts = Facts { snapshot: &self.snapshot, liveness: &self.live, expanded: &self.expanded, active: self.active.as_ref(), notice: self.notice.as_deref(), loaded: self.loaded };
        self.layout = ui::layout(&facts, self.size.0 as usize, self.size.1 as usize);
        let (max_x, max_y) = self.layout.max_scroll();
        self.ui.scroll_x = self.ui.scroll_x.min(max_x);
        self.ui.scroll_y = self.ui.scroll_y.min(max_y);
        // a focused widget that is gone or disabled loses the focus
        if let Some(key) = &self.ui.focus {
            if !self.layout.widgets.iter().any(|w| &w.key == key && w.button && w.enabled) {
                self.ui.focus = None;
            }
        }
    }

    fn draw(&mut self, terminal: &mut ratatui::DefaultTerminal, _again: bool) -> std::io::Result<()> {
        let size = terminal.size()?;
        self.size = (size.width, size.height);
        self.facts_layout();
        let (ui_state, layout, pointer) = (&self.ui, &self.layout, self.pointer);
        let (tooltip, toast) = (self.tooltip.clone(), self.toast.as_ref().map(|t| t.0.clone()));
        terminal.draw(|frame| {
            let buf = frame.buffer_mut();
            ui::paint(buf, layout, ui_state);
            if let Some(text) = &tooltip {
                ui::paint_tooltip(buf, text, pointer);
            }
            if let Some(text) = &toast {
                ui::paint_toast(buf, text);
            }
        })?;
        Ok(())
    }

    fn widget_at(&self, x: u16, y: u16) -> Option<Key> {
        match ui::hit(&self.layout, &self.ui, x as usize, y as usize) {
            Hit::Button(widget) => Some(widget.key.clone()),
            _ => None,
        }
    }

    /// The widget under the pointer for hover and tooltip: a text row with a tooltip (the Leader row) counts too.
    fn hover_target(&self, x: u16, y: u16) -> Option<Key> {
        match ui::hit(&self.layout, &self.ui, x as usize, y as usize) {
            Hit::Button(widget) => Some(widget.key.clone()),
            Hit::Static(widget) if widget.tooltip.is_some() => Some(widget.key.clone()),
            _ => None,
        }
    }

    fn input(&mut self, event: Event) -> bool {
        match event {
            Event::Resize(width, height) => {
                self.size = (width, height);
                true
            }
            Event::FocusLost => self.hide_tooltip(),
            Event::FocusGained => false,
            Event::Key(key) if key.kind != KeyEventKind::Release => {
                let hidden = self.hide_tooltip();
                self.key(key.code, key.modifiers) || hidden
            }
            Event::Mouse(mouse) => {
                let (x, y) = (mouse.column, mouse.row);
                match mouse.kind {
                    MouseEventKind::Moved | MouseEventKind::Drag(_) => self.hover(x, y),
                    MouseEventKind::Down(MouseButton::Left) => {
                        let mut dirty = self.hover(x, y);
                        self.mouse_down = self.widget_at(x, y);
                        if let Some(key) = self.mouse_down.clone() {
                            if self.layout.widgets.iter().any(|w| w.key == key && w.enabled) {
                                self.ui.focus = Some(key);
                                dirty = true;
                            }
                        }
                        dirty
                    }
                    MouseEventKind::Up(MouseButton::Left) => {
                        let target = self.widget_at(x, y);
                        let pressed = self.mouse_down.take();
                        if target.is_some() && target == pressed {
                            self.press(target.unwrap(), None);
                        }
                        false
                    }
                    MouseEventKind::ScrollDown if mouse.modifiers.intersects(KeyModifiers::SHIFT | KeyModifiers::CONTROL) => self.scroll(ui::SCROLL_STEP_X, 0),
                    MouseEventKind::ScrollUp if mouse.modifiers.intersects(KeyModifiers::SHIFT | KeyModifiers::CONTROL) => self.scroll(-ui::SCROLL_STEP_X, 0),
                    MouseEventKind::ScrollDown => self.scroll(0, ui::SCROLL_STEP_Y),
                    MouseEventKind::ScrollUp => self.scroll(0, -ui::SCROLL_STEP_Y),
                    MouseEventKind::ScrollRight => self.scroll(ui::SCROLL_STEP_X, 0),
                    MouseEventKind::ScrollLeft => self.scroll(-ui::SCROLL_STEP_X, 0),
                    _ => false,
                }
            }
            _ => false,
        }
    }

    fn hover(&mut self, x: u16, y: u16) -> bool {
        self.pointer = (x, y);
        let hover = self.hover_target(x, y);
        self.tooltip_expires = Some(Instant::now() + TOOLTIP_IDLE);
        if hover == self.ui.hover {
            return false;
        }
        self.ui.hover = hover.clone();
        let had = self.hide_tooltip();
        if let Some(key) = hover {
            if self.layout.widgets.iter().any(|w| w.key == key && w.tooltip.is_some()) {
                self.tooltip_due = Some((Instant::now() + TOOLTIP_DELAY, key));
            }
        }
        let _ = had;
        true
    }

    fn scroll(&mut self, dx: i32, dy: i32) -> bool {
        let (max_x, max_y) = self.layout.max_scroll();
        let nx = (self.ui.scroll_x as i32 + dx).clamp(0, max_x as i32) as usize;
        let ny = (self.ui.scroll_y as i32 + dy).clamp(0, max_y as i32) as usize;
        let changed = (nx, ny) != (self.ui.scroll_x, self.ui.scroll_y);
        self.ui.scroll_x = nx;
        self.ui.scroll_y = ny;
        changed
    }

    fn key(&mut self, code: KeyCode, modifiers: KeyModifiers) -> bool {
        let page = self.layout.view_h.max(1) as i32;
        match code {
            KeyCode::Char('q') if modifiers.contains(KeyModifiers::CONTROL) => {
                self.quit = true;
                false
            }
            KeyCode::Tab => self.move_focus(1),
            KeyCode::BackTab => self.move_focus(-1),
            KeyCode::Enter | KeyCode::Char(' ') => {
                if let Some(key) = self.ui.focus.clone() {
                    self.press(key, None);
                }
                false
            }
            KeyCode::Up => self.scroll(0, -1),
            KeyCode::Down => self.scroll(0, 1),
            KeyCode::Left => self.scroll(-1, 0),
            KeyCode::Right => self.scroll(1, 0),
            KeyCode::PageUp if modifiers.contains(KeyModifiers::CONTROL) => self.scroll(-(self.layout.view_w as i32), 0),
            KeyCode::PageDown if modifiers.contains(KeyModifiers::CONTROL) => self.scroll(self.layout.view_w as i32, 0),
            KeyCode::PageUp => self.scroll(0, -page),
            KeyCode::PageDown => self.scroll(0, page),
            KeyCode::Home => self.scroll(i32::MIN / 2, i32::MIN / 2),
            KeyCode::End => self.scroll(0, i32::MAX / 2),
            _ => false,
        }
    }

    /// Tab order is the order of the widgets in the blocks; a disabled button is skipped.
    fn move_focus(&mut self, step: i32) -> bool {
        let focusable: Vec<usize> = self.layout.widgets.iter().enumerate().filter(|(_, w)| w.button && w.enabled).map(|(i, _)| i).collect();
        if focusable.is_empty() {
            return false;
        }
        let current = self.ui.focus.as_ref().and_then(|key| focusable.iter().position(|i| &self.layout.widgets[*i].key == key));
        let next = match current {
            Some(position) => (position as i32 + step).rem_euclid(focusable.len() as i32) as usize,
            None => if step > 0 { 0 } else { focusable.len() - 1 },
        };
        let widget = self.layout.widgets[focusable[next]].clone();
        self.ui.focus = Some(widget.key.clone());
        self.scroll_into_view(&widget);
        true
    }

    fn scroll_into_view(&mut self, widget: &ui::Widget) {
        let height = self.layout.view_h as i64;
        let (top, bottom) = (widget.y as i64, (widget.y + widget.height) as i64);
        let scroll_y = self.ui.scroll_y as i64;
        if top < scroll_y {
            self.ui.scroll_y = top as usize;
        } else if bottom > scroll_y + height {
            self.ui.scroll_y = (bottom - height).max(0) as usize;
        }
        let width = self.layout.view_w as i64;
        let (left, right) = (widget.x as i64, (widget.x + widget.width.min(widget.auto_width.max(1))) as i64);
        let scroll_x = self.ui.scroll_x as i64;
        if left < scroll_x {
            self.ui.scroll_x = left as usize;
        } else if right > scroll_x + width {
            self.ui.scroll_x = (right - width).max(0) as usize;
        }
    }

    /// A button pressed from the keyboard or the pointer: it acts without a tmux client.
    fn press(&mut self, key: Key, client: Option<&str>) {
        let Some(widget) = self.layout.widgets.iter().find(|w| w.key == key && w.button && w.enabled) else { return };
        if let Some(action) = widget.action.clone() {
            self.activate(action, client);
        }
    }

    fn activate(&mut self, action: Action, client: Option<&str>) {
        let mut args: Vec<String> = Vec::new();
        match &action {
            Action::Fold(project) => {
                // shown at once; the helper then writes the shared option and the real value is read back
                if !self.expanded.remove(project) {
                    self.expanded.insert(project.clone());
                }
                args.extend(["toggle-fold".into(), "--project".into(), project.clone()]);
            }
            Action::Project(project) => args.extend(["switch-project".into(), "--project".into(), project.clone()]),
            Action::Cr(project, state) => args.extend(["open-cr".into(), "--project".into(), project.clone(), "--state".into(), (*state).into()]),
            Action::Decision(project) => args.extend(["open-decision".into(), "--project".into(), project.clone()]),
            Action::Seat(project, index) => args.extend(["switch-seat".into(), "--project".into(), project.clone(), "--seat".into(), index.to_string()]),
        }
        if !matches!(action, Action::Fold(_)) {
            if let Some(client) = client {
                args.extend(["--client".into(), client.to_string()]);
            }
        }
        let (tx, config, folding) = (self.tx.clone(), self.config.config.clone(), matches!(action, Action::Fold(_)));
        std::thread::spawn(move || {
            let result = tmuxio::run_helper(config.as_deref(), &args);
            if folding {
                // the shared value, whatever the helper did
                let _ = tx.send(Msg::Expanded(Tmux::from_env().refresh(false).0));
            }
            if let Err(message) = result {
                let _ = tx.send(Msg::Toast(message));
            }
        });
    }

    /// The click socket's request: the widget under the pane-relative cell, as `dispatch_client_click`.
    fn dispatch_client_click(&mut self, client: &str, x: i64, y: i64) -> Value {
        self.facts_layout();
        let (xu, yu) = (x as usize, y as usize);
        match ui::hit(&self.layout, &self.ui, xu, yu) {
            Hit::Outside => click_error("no_widget", "이 위치에는 조작할 항목이 없습니다."),
            Hit::Nothing | Hit::Static(_) => click_error("not_clickable", "이 항목은 클릭할 수 없습니다."),
            Hit::Button(widget) => {
                let (id, enabled, action) = (widget.id.clone(), widget.enabled, widget.action.clone());
                if !enabled {
                    // an empty count, a decision list without entries and a seat without a Worker do nothing
                    return match action {
                        Some(Action::Cr(..)) | Some(Action::Decision(_)) | Some(Action::Seat(..)) => json!({"ok": true, "data": {"widget": id}, "error": null}),
                        _ => click_error("not_clickable", "이 항목은 클릭할 수 없습니다."),
                    };
                }
                if let Some(action) = action {
                    self.activate(action, Some(client));
                }
                json!({"ok": true, "data": {"widget": id}, "error": null})
            }
        }
    }
}
