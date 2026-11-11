//! The sidebar drawn like the Textual `SidebarApp` of 0.7.1 (its CSS and `_project_block`): layout of the
//! rows, the colours of every state, hover, focus, the scroll bars and the tooltip.
//!
//! `layout` turns the facts into widgets placed on a virtual canvas, `paint` draws the canvas through the
//! scroll offsets into a ratatui buffer. Both are pure, so the cells can be compared with what Textual drew.
use crate::model::{Liveness, Project, Seat, Snapshot};
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};
use std::collections::HashSet;
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Rgb(pub u8, pub u8, pub u8);

pub const BG: Rgb = Rgb(0x11, 0x1c, 0x28);
const TOP_ERROR: Rgb = Rgb(0xff, 0xb8, 0x6c);
const STATIC_FG: Rgb = Rgb(0xe0, 0xe0, 0xe0);
const NAME: Rgb = Rgb(0xe6, 0xf0, 0xff);
const COUNT: Rgb = Rgb(0xd6, 0xe5, 0xf5);
const DECISION: Rgb = Rgb(0xff, 0xd4, 0x79);
const DECISION_OPEN: Rgb = Rgb(0xff, 0x8f, 0x8f);
const SEAT: Rgb = Rgb(0xc7, 0xdb, 0xf1);
const SEAT_EMPTY: Rgb = Rgb(0x77, 0x85, 0x96);
const PENDING: Rgb = Rgb(0xff, 0xcb, 0x84);
const STOPPED: Rgb = Rgb(0xff, 0x8f, 0x8f);
const ACTIVE_BG: Rgb = Rgb(0x2f, 0x6d, 0xb3);
const WHITE: Rgb = Rgb(0xff, 0xff, 0xff);
const HOVER_BG: Rgb = Rgb(0x34, 0x50, 0x6d);
const TOOLTIP_BG: Rgb = Rgb(0x24, 0x2f, 0x38);
const THUMB: Rgb = Rgb(0x00, 0x30, 0x54);
const TRACK: Rgb = Rgb(0, 0, 0);
const TOAST_BG: Rgb = Rgb(0x5a, 0x1f, 0x1f);
/// Textual's `Button:disabled` shows a button at this opacity over the screen.
const DISABLED_OPACITY: f32 = 0.42;
/// `background-tint: $foreground 5%` of `Button:focus`; `$foreground` is e0e0e0.
const FOCUS_TINT: f32 = 0.05;

pub const SCROLL_STEP_Y: i32 = 2;
pub const SCROLL_STEP_X: i32 = 4;

fn blend(front: Rgb, back: Rgb, alpha: f32) -> Rgb {
    let mix = |f: u8, b: u8| ((f as f32) * alpha + (b as f32) * (1.0 - alpha)).floor() as u8;
    Rgb(mix(front.0, back.0), mix(front.1, back.1), mix(front.2, back.2))
}

fn color(c: Rgb) -> Color {
    Color::Rgb(c.0, c.1, c.2)
}

pub fn text_width(s: &str) -> usize {
    UnicodeWidthStr::width(s)
}

/// Rows of text broken at spaces to at most `width` cells; a word wider than that is cut. Always one line at least.
pub fn wrap(text: &str, width: usize) -> Vec<String> {
    let width = width.max(1);
    let mut lines = Vec::new();
    for paragraph in text.split('\n') {
        let mut line = String::new();
        let mut line_width = 0;
        for word in paragraph.split(' ') {
            let word_width = text_width(word);
            if line_width > 0 && line_width + 1 + word_width > width {
                lines.push(std::mem::take(&mut line));
                line_width = 0;
            }
            if line_width > 0 {
                line.push(' ');
                line_width += 1;
            }
            if word_width > width {
                for ch in word.chars() {
                    let w = ch.width().unwrap_or(0);
                    if line_width + w > width {
                        lines.push(std::mem::take(&mut line));
                        line_width = 0;
                    }
                    line.push(ch);
                    line_width += w;
                }
            } else {
                line.push_str(word);
                line_width += word_width;
            }
        }
        lines.push(line);
    }
    lines
}

/// `2d 01h 00m`, `3h 05m`, `12m`: whole minutes, without leading zero units (docs/project-board-tui-plan.md section 3).
pub fn format_elapsed(seconds: Option<i64>) -> Option<String> {
    let minutes_total = seconds?.max(0) / 60;
    let (days, rest) = (minutes_total / 1440, minutes_total % 1440);
    let (hours, minutes) = (rest / 60, rest % 60);
    Some(if days > 0 {
        format!("{days}d {hours:02}h {minutes:02}m")
    } else if hours > 0 {
        format!("{hours}h {minutes:02}m")
    } else {
        format!("{minutes}m")
    })
}

pub fn seat_text(seat: &Seat) -> String {
    let prefix = match seat.status.as_str() {
        "reviewing" => "R ",
        "pending" => "대기 ",
        "release_pending" => "반납대기 ",
        _ => "  ",
    };
    let host = seat.host.as_ref().map(|h| format!("@{h}")).unwrap_or_default();
    let text = format!("{prefix}{}{host} {}", seat.index, seat.job_id.as_deref().unwrap_or("-"));
    match format_elapsed(seat.elapsed) {
        Some(elapsed) => format!("{text} {elapsed}"),
        None => text,
    }
}

/// The managed tmux window this pane is in (`active_context`): a project and a slot (`leader`, `seat-N`).
#[derive(Clone, PartialEq, Eq, Debug, Default)]
pub struct Active {
    pub project_id: String,
    pub slot: Option<String>,
}

#[derive(Clone, PartialEq, Eq, Hash, Debug)]
pub enum Role {
    Name,
    Decision,
    /// 0 open, 1 todo, 2 in-progress
    Count(usize),
    Fold,
    Seat(usize),
    Error(usize),
}

/// The stable identity of a widget: it survives a refresh, so focus and hover do too.
#[derive(Clone, PartialEq, Eq, Hash, Debug)]
pub struct Key {
    pub project: String,
    pub role: Role,
}

/// What a click or Enter does (`SidebarApp._actions`).
#[derive(Clone, PartialEq, Eq, Debug)]
pub enum Action {
    Fold(String),
    Project(String),
    Cr(String, &'static str),
    Decision(String),
    Seat(String, usize),
}

#[derive(Clone, Debug)]
pub struct Widget {
    pub key: Key,
    /// The widget id of the 0.7.1 sidebar (`project-<n>-name`, `-D`, `-O`, `-seat-<i>` ...); the click socket answers with it.
    pub id: String,
    pub button: bool,
    pub enabled: bool,
    pub label: String,
    /// Cells of padding before and after the label of a button (Textual's `line-pad`).
    pub pad: usize,
    /// Cells after the button that belong to it (`padding-right`).
    pub trail: usize,
    /// The width the widget takes when it is laid out `auto`.
    pub auto_width: usize,
    /// Rows of an error or empty-list text (a Static that wraps).
    pub lines: Vec<String>,
    pub x: usize,
    pub y: usize,
    /// Own width; a `fill` widget is as wide as its block instead.
    pub width: usize,
    pub fill: bool,
    pub height: usize,
    pub fg: Rgb,
    pub bold: bool,
    pub active: bool,
    pub class_error: bool,
    pub tooltip: Option<String>,
    pub action: Option<Action>,
    pub project_index: usize,
}

#[derive(Default)]
pub struct Layout {
    pub widgets: Vec<Widget>,
    pub block_width: Vec<usize>,
    pub top_lines: Vec<String>,
    pub virtual_w: usize,
    pub virtual_h: usize,
    pub vbar: bool,
    pub hbar: bool,
    pub view_w: usize,
    pub view_h: usize,
    pub screen_w: usize,
    pub screen_h: usize,
}

impl Layout {
    pub fn max_scroll(&self) -> (usize, usize) {
        (self.virtual_w.saturating_sub(self.view_w), self.virtual_h.saturating_sub(self.view_h))
    }
    pub fn top_height(&self) -> usize {
        self.top_lines.len()
    }
}

pub struct Facts<'a> {
    pub snapshot: &'a Snapshot,
    pub liveness: &'a Liveness,
    pub expanded: &'a HashSet<String>,
    pub active: Option<&'a Active>,
    /// Shown on the first row when the snapshot has no error (a click socket that could not be opened).
    pub notice: Option<&'a str>,
    /// A snapshot has been read; until then an empty list is not yet "no project".
    pub loaded: bool,
}

fn count_label(project: &Project, index: usize) -> String {
    match &project.cr {
        Some(counts) => [counts.open, counts.todo, counts.in_progress][index].to_string(),
        None => if project.errors.iter().any(|e| e.source == "cr") { "!".into() } else { "-".into() },
    }
}

fn decide_label(project: &Project) -> String {
    match &project.decide {
        Some(decide) => decide.open.to_string(),
        None => if project.errors.iter().any(|e| e.source == "decide") { "!".into() } else { "-".into() },
    }
}

fn seat_liveness<'a>(facts: &'a Facts, project: &Project, seat: &Seat) -> Option<&'a str> {
    let row = facts.liveness.get(&project.id)?.get(&seat.index.to_string())?;
    if Some(row.session_id.as_str()) != seat.session_id.as_deref() {
        return None;
    }
    Some(row.state.as_str())
}

fn button(project: &Project, number: usize, role: Role, id_suffix: String, label: String, pad: usize) -> Widget {
    Widget {
        key: Key { project: project.id.clone(), role },
        id: format!("project-{number}-{id_suffix}"),
        button: true,
        enabled: true,
        auto_width: text_width(&label) + 2,
        label,
        pad,
        trail: 0,
        lines: Vec::new(),
        x: 0,
        y: 0,
        width: 0,
        fill: false,
        height: 1,
        fg: COUNT,
        bold: true,
        active: false,
        class_error: false,
        tooltip: None,
        action: None,
        project_index: number,
    }
}

/// The widgets of one project, rows relative to the block, in the order of `_project_block`.
fn project_widgets(facts: &Facts, number: usize, project: &Project, out: &mut Vec<Widget>) {
    let expanded = facts.expanded.contains(&project.id);
    let is_active = facts.active.map_or(false, |a| a.project_id == project.id);
    let slot: Option<&str> = if is_active { facts.active.and_then(|a| a.slot.as_deref()) } else { None };

    // `{project} {time}`: the time is the Leader's, folded or expanded; no time without a Leader session (BOARD-023).
    let time = format_elapsed(project.leader.as_ref().and_then(|l| l.elapsed));
    let label = format!("{}{}{}", if is_active { "▶ " } else { "" }, project.id, time.as_ref().map(|t| format!(" {t}")).unwrap_or_default());
    let mut name = button(project, number, Role::Name, "name".into(), label, 0);
    name.fill = true;
    name.fg = NAME;
    name.active = is_active;
    name.tooltip = Some(if time.is_some() { format!("{} · Leader session이 게시된 뒤 지난 시간", project.id) } else { project.id.clone() });
    name.action = Some(Action::Project(project.id.clone()));
    out.push(name);

    let label = decide_label(project);
    let mut decision = button(project, number, Role::Decision, "D".into(), format!("D:{label}"), 1);
    decision.fill = true;
    decision.enabled = project.decide.as_ref().map_or(false, |d| d.visible() > 0);
    decision.fg = if !matches!(label.as_str(), "-" | "!" | "0") { DECISION_OPEN } else { DECISION };
    let stages = project.decide.as_ref().map(|d| d.stages).unwrap_or([0; 4]);
    decision.tooltip = Some(
        ["결정 대기", "답변 접수", "반영 중", "완료"].iter().zip(stages)
            .map(|(name, count)| format!("{name} {count}")).collect::<Vec<_>>().join(" · "),
    );
    decision.action = Some(Action::Decision(project.id.clone()));
    out.push(decision);

    for (index, (short, state)) in [("O", "open"), ("T", "todo"), ("I", "in-progress")].into_iter().enumerate() {
        let label = count_label(project, index);
        let mut count = button(project, number, Role::Count(index), short.into(), format!("{short}:{label}"), 1);
        count.trail = 1;
        count.auto_width += 1;
        count.enabled = !matches!(label.as_str(), "-" | "!" | "0");
        count.action = Some(Action::Cr(project.id.clone(), state));
        out.push(count);
    }
    // A Leader window is shown by the name row (BOARD-023); only a seat slot hides behind the fold button.
    let slot_hidden = slot.map_or(false, |slot| slot.starts_with("seat-")) && !expanded;
    let mut fold = button(project, number, Role::Fold, "seats".into(), (if expanded { "▾" } else { "▸" }).into(), 1);
    let mut tooltip = (if expanded { "좌석 접기" } else { "좌석 펼치기" }).to_string();
    if slot_hidden {
        let slot = slot.unwrap_or("");
        tooltip.push_str(" · 현재 창: ");
        tooltip.push_str(&slot.replace('-', " "));
    }
    fold.tooltip = Some(tooltip);
    fold.active = slot_hidden;
    fold.action = Some(Action::Fold(project.id.clone()));
    out.push(fold);

    if expanded {
        for seat in &project.seats {
            let label = seat_text(seat);
            let mut widget = button(project, number, Role::Seat(seat.index), format!("seat-{}", seat.index), label, 1);
            widget.fill = true;
            let live = seat_liveness(facts, project, seat);
            widget.enabled = seat.job_id.is_some() && seat.session_id.is_some();
            widget.fg = if live == Some("unknown") {
                PENDING
            } else if live == Some("stopped") {
                STOPPED
            } else if seat.job_id.is_some() && matches!(seat.status.as_str(), "pending" | "release_pending") {
                PENDING
            } else if seat.job_id.is_none() {
                SEAT_EMPTY
            } else {
                SEAT
            };
            widget.active = slot == Some(format!("seat-{}", seat.index).as_str());
            let mut tooltip = match (&seat.title, &seat.job_id) {
                (Some(title), Some(job)) if !title.is_empty() => format!("{job}: {title}"),
                (_, Some(job)) => job.clone(),
                _ => format!("{} -", seat.index),
            };
            if let Some(host) = &seat.host {
                tooltip.push_str(&format!(" · 호스트: {host} · {}", seat.path));
            }
            if seat.status == "pending" {
                tooltip.push_str(" · 시작 대기");
            } else if seat.status == "release_pending" {
                tooltip.push_str(" · 반납 대기: Worker는 끝났고 CR이 in-progress에 있습니다. CR을 옮기면 반납됩니다");
            }
            if live == Some("stopped") {
                tooltip.push_str(" · 실행 종료");
            } else if live == Some("unknown") {
                tooltip.push_str(" · 실행 확인 불가");
            }
            widget.tooltip = Some(tooltip);
            widget.action = Some(Action::Seat(project.id.clone(), seat.index));
            out.push(widget);
        }
    }
    for (index, error) in project.errors.iter().enumerate() {
        let text = format!("{}: {}", error.source, error.message);
        let mut widget = button(project, number, Role::Error(index), format!("error-{index}"), text, 0);
        widget.button = false;
        widget.fg = DECISION_OPEN;
        widget.bold = false;
        widget.class_error = true;
        out.push(widget);
    }
}

/// Place everything for a screen of `screen_w` x `screen_h` cells. The scroll bars of `#projects` appear
/// when the content is larger than its viewport; each one shrinks the viewport of the other.
pub fn layout(facts: &Facts, screen_w: usize, screen_h: usize) -> Layout {
    let top_text = facts.snapshot.error.as_deref().or(facts.notice).unwrap_or("");
    let top_lines = wrap(top_text, screen_w);
    let mut per_project: Vec<Vec<Widget>> = Vec::new();
    for (number, project) in facts.snapshot.projects.iter().enumerate() {
        let mut widgets = Vec::new();
        project_widgets(facts, number, project, &mut widgets);
        per_project.push(widgets);
    }
    let region_h = screen_h.saturating_sub(top_lines.len());
    let (mut vbar, mut hbar) = (false, false);
    let mut result = Layout::default();
    for _ in 0..4 {
        let view_w = screen_w.saturating_sub(if vbar { 2 } else { 0 }).max(1);
        let view_h = region_h.saturating_sub(if hbar { 1 } else { 0 });
        result = place(&per_project, view_w, view_h, facts.loaded);
        // Textual compares the content width with the width of the whole container, not the one left by the vertical bar
        // (measured: a 24 cell row in a 25 cell pane with a vertical bar scrolls by one cell and has no horizontal bar).
        let (need_v, need_h) = (vbar || result.virtual_h > view_h, hbar || result.virtual_w > screen_w);
        if (need_v, need_h) == (vbar, hbar) {
            break;
        }
        vbar = need_v;
        hbar = need_h;
    }
    result.top_lines = top_lines;
    result.vbar = vbar;
    result.hbar = hbar;
    result.screen_w = screen_w;
    result.screen_h = screen_h;
    result
}

fn place(per_project: &[Vec<Widget>], view_w: usize, view_h: usize, loaded: bool) -> Layout {
    let mut layout = Layout { view_w, view_h, ..Layout::default() };
    let mut y = 0;
    if per_project.is_empty() {
        if !loaded {
            return layout;
        }
        let mut empty = Widget {
            key: Key { project: String::new(), role: Role::Error(0) },
            id: "empty".into(),
            button: false,
            enabled: true,
            label: String::new(),
            pad: 0,
            trail: 0,
            auto_width: 0,
            lines: wrap("등록된 project가 없습니다.", view_w),
            x: 0,
            y: 0,
            width: view_w,
            fill: false,
            height: 0,
            fg: STATIC_FG,
            bold: false,
            active: false,
            class_error: false,
            tooltip: None,
            action: None,
            project_index: 0,
        };
        empty.height = empty.lines.len();
        layout.virtual_h = empty.height;
        layout.virtual_w = view_w;
        layout.widgets.push(empty);
        return layout;
    }
    for widgets in per_project {
        let auto = widgets.iter().filter(|w| !matches!(w.key.role, Role::Error(_)))
            .map(|w| match w.key.role {
                Role::Count(_) | Role::Fold => 0,
                _ => w.auto_width,
            })
            .max().unwrap_or(0);
        let counts: usize = widgets.iter().filter(|w| matches!(w.key.role, Role::Count(_) | Role::Fold))
            .map(|w| w.auto_width).sum();
        let block = view_w.max(auto).max(counts);
        layout.block_width.push(block);
        let mut x = 0;
        let mut counts_row: Option<usize> = None;
        for widget in widgets {
            let mut widget = widget.clone();
            match widget.key.role {
                Role::Count(_) | Role::Fold => {
                    let row = *counts_row.get_or_insert_with(|| {
                        let row = y;
                        y += 1;
                        row
                    });
                    widget.y = row;
                    widget.x = x;
                    widget.width = widget.auto_width;
                    x += widget.auto_width;
                }
                Role::Error(_) => {
                    widget.lines = wrap(&widget.label, block);
                    widget.height = widget.lines.len();
                    widget.y = y;
                    widget.x = 0;
                    widget.width = block;
                    y += widget.height;
                }
                _ => {
                    widget.y = y;
                    widget.x = 0;
                    widget.width = block;
                    y += 1;
                }
            }
            layout.widgets.push(widget);
        }
        y += 1; // margin-bottom: 1
        layout.virtual_w = layout.virtual_w.max(block);
    }
    layout.virtual_h = y;
    layout
}

/// What changes the look of a widget while it is shown.
#[derive(Clone, Default)]
pub struct Interaction {
    pub hover: Option<Key>,
    pub focus: Option<Key>,
    pub scroll_x: usize,
    pub scroll_y: usize,
}

struct Look {
    fg: Option<Rgb>,
    bg: Rgb,
    bold: bool,
    reverse: bool,
}

fn style_of(widget: &Widget, hovered: bool, focused: bool) -> Look {
    let mut look = Look { fg: Some(widget.fg), bg: BG, bold: widget.bold, reverse: false };
    if !widget.button {
        if widget.active {
            look = Look { fg: Some(WHITE), bg: ACTIVE_BG, bold: true, reverse: false };
        }
        return look;
    }
    let is_name = widget.key.role == Role::Name;
    let is_seat = matches!(widget.key.role, Role::Seat(_));
    if widget.active {
        look = Look { fg: Some(WHITE), bg: ACTIVE_BG, bold: true, reverse: false };
    }
    // `.seat:hover` is more specific than `.slot-active`; for the name and the fold button the active rule is the later one.
    if hovered && (!widget.active || is_seat) {
        look.bg = HOVER_BG;
    }
    if focused {
        if is_name || widget.active {
            // their own `text-style: bold` replaces the `reverse` of Button:focus; the tint of the focus stays
            if look.bg != BG {
                look.bg = blend(STATIC_FG, look.bg, FOCUS_TINT);
            }
        } else {
            look.reverse = true;
        }
    }
    if !widget.enabled {
        let faded = blend(look.fg.unwrap_or(STATIC_FG), BG, DISABLED_OPACITY);
        if hovered {
            // measured on Textual: a disabled button under the pointer shows 213549, its text lifted by it
            let bg = Rgb(0x21, 0x35, 0x49);
            let lift = |text: u8, under: u8, screen: u8| (text as f32 + (under as f32 - screen as f32) * 0.4) as u8;
            look.fg = Some(Rgb(lift(faded.0, bg.0, BG.0), lift(faded.1, bg.1, BG.1), lift(faded.2, bg.2, BG.2)));
            look.bg = bg;
        } else {
            look.fg = Some(faded);
        }
    }
    look
}

fn style(look: &Look) -> Style {
    let mut s = Style::default().bg(color(look.bg));
    if let Some(fg) = look.fg {
        s = s.fg(color(fg));
    }
    if look.bold {
        s = s.add_modifier(Modifier::BOLD);
    }
    if look.reverse {
        s = s.add_modifier(Modifier::REVERSED);
    }
    s
}

fn put(buf: &mut Buffer, x: i64, y: i64, text: &str, style: Style, clip: Rect) {
    // `text` starts at virtual column x; only the cells inside `clip` are written.
    if y < clip.y as i64 || y >= (clip.y + clip.height) as i64 {
        return;
    }
    let mut cx = x;
    for ch in text.chars() {
        let w = ch.width().unwrap_or(0) as i64;
        if w == 0 {
            continue;
        }
        if cx >= clip.x as i64 && cx + w <= (clip.x + clip.width) as i64 {
            let cell = &mut buf[(cx as u16, y as u16)];
            cell.set_symbol(ch.encode_utf8(&mut [0; 4]));
            cell.set_style(style);
            if w == 2 {
                buf[(cx as u16 + 1, y as u16)].set_style(style);
            }
        }
        cx += w;
    }
}

fn fill_cells(buf: &mut Buffer, x: i64, y: i64, count: usize, style: Style, clip: Rect) {
    put(buf, x, y, &" ".repeat(count), style, clip);
}

/// `ScrollBarRender.render_bar` of Textual: the thumb and its eighth-block ends.
fn bar_cells(size: usize, virtual_size: usize, window: usize, position: usize, vertical: bool) -> Vec<(String, Style)> {
    const VERTICAL: [&str; 8] = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", " "];
    const HORIZONTAL: [&str; 8] = ["▉", "▊", "▋", "▌", "▍", "▎", "▏", " "];
    let bars = if vertical { &VERTICAL } else { &HORIZONTAL };
    let back = Style::default().bg(color(TRACK));
    let thumb_reverse = Style::default().fg(color(THUMB)).bg(color(BG)).add_modifier(Modifier::REVERSED);
    let mut cells: Vec<(String, Style)> = vec![(" ".into(), back); size];
    if window == 0 || size == 0 || virtual_size == 0 || size == virtual_size {
        return cells;
    }
    let bar_ratio = virtual_size as f64 / size as f64;
    let thumb_size = (window as f64 / bar_ratio).max(1.0);
    let denominator = (virtual_size - window).max(1) as f64;
    let position_ratio = position as f64 / denominator;
    let position = (size as f64 - thumb_size) * position_ratio;
    let start = (position * 8.0) as i64;
    let end = start + (thumb_size * 8.0).ceil() as i64;
    let (start_index, start_bar) = ((start.max(0) / 8) as usize, (start.max(0) % 8) as usize);
    let (end_index, end_bar) = ((end.max(0) / 8) as usize, (end.max(0) % 8) as usize);
    for cell in cells.iter_mut().take(end_index.min(size)).skip(start_index) {
        *cell = (" ".into(), thumb_reverse);
    }
    if start_index < size {
        let glyph = bars[7 - start_bar];
        if glyph != " " {
            let style = if vertical {
                Style::default().fg(color(THUMB)).bg(color(TRACK))
            } else {
                Style::default().fg(color(THUMB)).bg(color(TRACK)).add_modifier(Modifier::REVERSED)
            };
            cells[start_index] = (glyph.to_string(), style);
        }
    }
    if end_index < size {
        let glyph = bars[7 - end_bar];
        if glyph != " " {
            let style = if vertical {
                Style::default().fg(color(THUMB)).bg(color(TRACK)).add_modifier(Modifier::REVERSED)
            } else {
                Style::default().fg(color(THUMB)).bg(color(TRACK))
            };
            cells[end_index] = (glyph.to_string(), style);
        }
    }
    cells
}

/// A widget's rectangle on the screen, or None when it is scrolled out. Used by `paint` and `hit`.
pub fn screen_rect(layout: &Layout, widget: &Widget, scroll: (usize, usize)) -> (i64, i64, usize, usize) {
    let block = layout.block_width.get(widget.project_index).copied().unwrap_or(layout.view_w);
    let width = if widget.fill { block } else { widget.width };
    let x = widget.x as i64 - scroll.0 as i64;
    let y = widget.y as i64 - scroll.1 as i64 + layout.top_height() as i64;
    (x, y, width, widget.height)
}

pub fn paint(buf: &mut Buffer, layout: &Layout, ui: &Interaction) {
    let area = *buf.area();
    let screen = Style::default().bg(color(BG));
    for y in area.y..area.y + area.height {
        for x in area.x..area.x + area.width {
            let cell = &mut buf[(x, y)];
            cell.reset();
            cell.set_style(screen);
        }
    }
    let top = layout.top_height();
    for (row, line) in layout.top_lines.iter().enumerate() {
        put(buf, 0, row as i64, line, Style::default().fg(color(TOP_ERROR)).bg(color(BG)), area);
    }
    let viewport = Rect { x: 0, y: top as u16, width: layout.view_w as u16, height: layout.view_h as u16 };
    let scroll = (ui.scroll_x, ui.scroll_y);
    for widget in &layout.widgets {
        let (x, y, width, height) = screen_rect(layout, widget, scroll);
        if y + height as i64 <= viewport.y as i64 || y >= (viewport.y + viewport.height) as i64 {
            continue;
        }
        if !widget.button {
            let look = style_of(widget, false, false);
            for row in 0..height {
                let text = widget.lines.get(row).map(String::as_str).unwrap_or(if widget.lines.is_empty() { widget.label.as_str() } else { "" });
                let body = Style::default().fg(color(look.fg.unwrap_or(STATIC_FG))).bg(color(look.bg))
                    .add_modifier(if look.bold { Modifier::BOLD } else { Modifier::empty() });
                put(buf, x, y + row as i64, text, body, viewport);
                let used = text_width(text);
                fill_cells(buf, x + used as i64, y + row as i64, width.saturating_sub(used), Style::default().bg(color(look.bg)), viewport);
            }
            continue;
        }
        let hovered = ui.hover.as_ref() == Some(&widget.key);
        let focused = ui.focus.as_ref() == Some(&widget.key);
        let look = style_of(widget, hovered, focused);
        let text_style = style(&look);
        let body = format!("{}{}{}", " ".repeat(widget.pad), widget.label, " ".repeat(widget.pad));
        put(buf, x, y, &body, text_style, viewport);
        let used = text_width(&body);
        // the rest of the widget: fill to the block, or the trailing padding of a count button
        let rest = width.saturating_sub(used);
        let rest_style = if widget.fill { text_style.remove_modifier(Modifier::REVERSED) } else { Style::default().bg(color(look.bg)) };
        fill_cells(buf, x + used as i64, y, rest, rest_style, viewport);
    }
    // scroll bars of #projects
    let (max_x, max_y) = layout.max_scroll();
    let _ = (max_x, max_y);
    if layout.vbar {
        let size = layout.view_h;
        for (row, (glyph, style)) in bar_cells(size, layout.virtual_h, layout.view_h, ui.scroll_y, true).into_iter().enumerate() {
            for col in 0..2 {
                put(buf, (layout.view_w + col) as i64, (top + row) as i64, &glyph, style, area);
            }
        }
    }
    if layout.hbar {
        let y = (top + layout.view_h) as i64;
        for (col, (glyph, style)) in bar_cells(layout.view_w, layout.virtual_w, layout.view_w, ui.scroll_x, false).into_iter().enumerate() {
            put(buf, col as i64, y, &glyph, style, area);
        }
        if layout.vbar {
            fill_cells(buf, layout.view_w as i64, y, 2, Style::default().bg(color(TRACK)), area);
        }
    }
}

/// The result of looking for the widget under a screen cell (`dispatch_client_click`).
#[derive(Debug)]
pub enum Hit<'a> {
    Outside,
    Nothing,
    Static(&'a Widget),
    Button(&'a Widget),
}

pub fn hit<'a>(layout: &'a Layout, ui: &Interaction, x: usize, y: usize) -> Hit<'a> {
    if x >= layout.screen_w || y >= layout.screen_h {
        return Hit::Outside;
    }
    let top = layout.top_height();
    if y < top || x >= layout.view_w || y >= top + layout.view_h {
        return Hit::Nothing;
    }
    let scroll = (ui.scroll_x, ui.scroll_y);
    for widget in &layout.widgets {
        let (wx, wy, width, height) = screen_rect(layout, widget, scroll);
        if (x as i64) >= wx && (x as i64) < wx + width as i64 && (y as i64) >= wy && (y as i64) < wy + height as i64 {
            return if widget.button { Hit::Button(widget) } else { Hit::Static(widget) };
        }
    }
    Hit::Nothing
}

/// A tooltip over the pane: the text in a box of `padding: 1 2` that is centred on the pointer (`offset-x: -50%`)
/// and kept inside the pane; below the pointer, or above it when there is no room.
pub fn paint_tooltip(buf: &mut Buffer, text: &str, pointer: (u16, u16)) {
    let area = *buf.area();
    if area.width < 5 || area.height < 3 {
        return;
    }
    let max_text = (area.width as usize - 4).min(36);
    let lines = wrap(text, max_text);
    let text_w = lines.iter().map(|l| text_width(l)).max().unwrap_or(0).max(1);
    let (w, h) = (text_w + 4, lines.len() + 2);
    let x = (pointer.0 as i64 - (w as i64) / 2).clamp(0, (area.width as i64 - w as i64).max(0));
    let below = pointer.1 as i64 + 1;
    let y = if below + h as i64 <= area.height as i64 { below } else { (pointer.1 as i64 - h as i64).max(0) };
    let body = Style::default().fg(color(STATIC_FG)).bg(color(TOOLTIP_BG));
    for row in 0..h {
        fill_cells(buf, x, y + row as i64, w, body, area);
        if row >= 1 && row <= lines.len() {
            put(buf, x + 2, y + row as i64, &lines[row - 1], body, area);
        }
    }
}

/// A message about a failed action, at the bottom of the pane (`App.notify(..., severity="error")`).
pub fn paint_toast(buf: &mut Buffer, text: &str) {
    let area = *buf.area();
    if area.width < 5 || area.height < 2 {
        return;
    }
    let lines = wrap(text, area.width as usize - 2);
    let h = lines.len().min(area.height as usize);
    let body = Style::default().fg(color(STATIC_FG)).bg(color(TOAST_BG));
    for (row, line) in lines.iter().take(h).enumerate() {
        let y = area.height as i64 - h as i64 + row as i64;
        fill_cells(buf, 0, y, area.width as usize, body, area);
        put(buf, 1, y, line, body, area);
    }
}

/// The cells of a buffer as runs of equal style, one list per row: the form the golden screens and the
/// comparison with the Textual dump use (`render` command).
pub fn runs(buf: &Buffer) -> Vec<Vec<(String, Option<String>, String, bool, bool)>> {
    let area = *buf.area();
    let hex = |c: Color| match c {
        Color::Rgb(r, g, b) => Some(format!("{r:02x}{g:02x}{b:02x}")),
        _ => None,
    };
    let mut rows = Vec::new();
    for y in area.y..area.y + area.height {
        let mut row: Vec<(String, Option<String>, String, bool, bool)> = Vec::new();
        let mut x = area.x;
        while x < area.x + area.width {
            let cell = &buf[(x, y)];
            let symbol = cell.symbol().to_string();
            let width = text_width(&symbol).max(1) as u16;
            let fg = hex(cell.fg);
            let bg = hex(cell.bg).unwrap_or_default();
            let bold = cell.modifier.contains(Modifier::BOLD);
            let reverse = cell.modifier.contains(Modifier::REVERSED);
            match row.last_mut() {
                Some(last) if last.1 == fg && last.2 == bg && last.3 == bold && last.4 == reverse => last.0.push_str(&symbol),
                _ => row.push((symbol, fg, bg, bold, reverse)),
            }
            x += width;
        }
        rows.push(row);
    }
    rows
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{CrCounts, Decide, Leader, ProjectError};

    // The expected texts are those of the Textual sidebar's tests (0.7.1 `test_tui.py`).
    #[test]
    fn elapsed_time_drops_zero_leading_units() {
        let cases = [
            (0, "0m"), (59, "0m"), (60, "1m"), (59 * 60, "59m"), (59 * 60 + 59, "59m"), (3600, "1h 00m"),
            (3 * 3600 + 5 * 60, "3h 05m"), (23 * 3600 + 59 * 60, "23h 59m"), (24 * 3600, "1d 00h 00m"),
            (2 * 86400 + 3600, "2d 01h 00m"), (12 * 86400 + 5 * 3600 + 9 * 60, "12d 05h 09m"), (-30, "0m"),
        ];
        for (seconds, text) in cases {
            assert_eq!(format_elapsed(Some(seconds)).as_deref(), Some(text), "{seconds}");
        }
        assert_eq!(format_elapsed(None), None);
    }

    fn seat(index: usize, job: Option<&str>, status: &str, host: Option<&str>, elapsed: Option<i64>) -> Seat {
        Seat { index, job_id: job.map(String::from), status: status.into(), host: host.map(String::from), elapsed, ..Seat::default() }
    }

    #[test]
    fn a_seat_row_names_the_state_the_host_the_job_and_the_time_when_known() {
        assert_eq!(seat_text(&seat(0, Some("TOOL-001"), "working", None, Some(11 * 3600 + 120))), "  0 TOOL-001 11h 02m");
        assert_eq!(seat_text(&seat(0, Some("TOOL-001"), "working", None, None)), "  0 TOOL-001");
        assert_eq!(seat_text(&seat(1, None, "empty", None, None)), "  1 -");
        assert_eq!(seat_text(&seat(0, Some("TOOL-001"), "release_pending", None, None)), "반납대기 0 TOOL-001");
        assert_eq!(seat_text(&seat(2, Some("TOOL-001"), "working", Some("macbook-worker"), None)), "  2@macbook-worker TOOL-001");
        assert_eq!(seat_text(&seat(0, Some("T-1"), "reviewing", None, None)), "R 0 T-1");
        assert_eq!(seat_text(&seat(0, Some("T-1"), "pending", None, None)), "대기 0 T-1");
    }

    #[test]
    fn text_wraps_at_spaces_and_cuts_a_word_wider_than_the_row() {
        assert_eq!(wrap("Each base key must be an absolute path or start with ~/.", 25),
                   ["Each base key must be an", "absolute path or start", "with ~/."]);
        assert_eq!(wrap("등록된 project가 없습니다.", 25), ["등록된 project가", "없습니다."]);
        assert_eq!(wrap("abcdefgh", 3), ["abc", "def", "gh"]);
        assert_eq!(wrap("", 10), [""]);
    }

    fn project(id: &str) -> Project {
        Project {
            id: id.into(),
            cr: Some(CrCounts { open: 2, todo: 0, in_progress: 1 }),
            decide: Some(Decide { open: 1, stages: [1, 0, 0, 0] }),
            leader: Some(Leader { elapsed: Some(600) }),
            seats: vec![
                Seat { index: 0, job_id: Some("T-1".into()), status: "working".into(), session: true, session_id: Some("s0".into()), ..Seat::default() },
                Seat { index: 1, status: "empty".into(), ..Seat::default() },
            ],
            ..Project::default()
        }
    }

    fn laid_out(snapshot: &Snapshot, expanded: &[&str], w: usize, h: usize) -> Layout {
        let live = Liveness::new();
        let expanded: HashSet<String> = expanded.iter().map(|s| s.to_string()).collect();
        layout(&Facts { snapshot, liveness: &live, expanded: &expanded, active: None, notice: None, loaded: true }, w, h)
    }

    #[test]
    fn a_click_finds_the_button_under_the_cell_and_says_what_it_is_not_when_it_is_none() {
        let snapshot = Snapshot { error: None, projects: vec![project("falcon"), project("other")] };
        let layout = laid_out(&snapshot, &["falcon"], 25, 30);
        let ui = Interaction::default();
        let id = |x: usize, y: usize| match hit(&layout, &ui, x, y) {
            Hit::Button(w) => w.id.clone(),
            Hit::Static(_) => "static".into(),
            Hit::Nothing => "nothing".into(),
            Hit::Outside => "outside".into(),
        };
        // 0 error row, 1 name, 2 decisions, 3 counts, 4-5 seats, 6 margin, 7 the next project
        assert_eq!(id(0, 0), "nothing");
        assert_eq!(id(24, 1), "project-0-name");
        assert_eq!(id(0, 2), "project-0-D");
        assert_eq!([0, 5, 6, 11, 12, 17, 18, 20].map(|x| id(x, 3)),
                   ["project-0-O", "project-0-O", "project-0-T", "project-0-T", "project-0-I", "project-0-I", "project-0-seats", "project-0-seats"]);
        assert_eq!(id(21, 3), "nothing");
        assert_eq!(id(3, 4), "project-0-seat-0");
        assert_eq!(id(3, 5), "project-0-seat-1");
        assert_eq!(id(3, 6), "nothing");
        assert_eq!(id(3, 7), "project-1-name");
        assert_eq!(id(25, 1), "outside");
        assert_eq!(id(3, 30), "outside");
    }

    #[test]
    fn a_count_of_nothing_or_an_unreadable_tree_is_dimmed_and_cannot_be_pressed() {
        let mut broken = project("broken");
        broken.cr = None;
        broken.decide = None;
        broken.errors = vec![ProjectError { source: "cr".into(), message: "bad".into() }];
        let snapshot = Snapshot { error: None, projects: vec![broken] };
        let layout = laid_out(&snapshot, &[], 30, 20);
        let label = |id: &str| layout.widgets.iter().find(|w| w.id == id).map(|w| (w.label.clone(), w.enabled)).unwrap();
        assert_eq!(label("project-0-O"), ("O:!".into(), false));
        assert_eq!(label("project-0-D"), ("D:-".into(), false));
    }

    #[test]
    fn the_scroll_bars_appear_when_the_content_is_larger_and_the_viewport_shrinks_for_each() {
        let snapshot = Snapshot { error: None, projects: (0..10).map(|n| project(&format!("p{n}"))).collect() };
        let tall = laid_out(&snapshot, &[], 25, 12);
        assert!(tall.vbar && !tall.hbar);
        assert_eq!((tall.view_w, tall.view_h), (23, 11));
        let fits = laid_out(&snapshot, &[], 25, 60);
        assert!(!fits.vbar && !fits.hbar);
        let narrow = laid_out(&Snapshot { error: None, projects: vec![project("falcon")] }, &[], 10, 30);
        assert!(narrow.hbar && !narrow.vbar);
        assert_eq!(narrow.view_h, 29 - 1);
        assert_eq!(narrow.max_scroll().0, 21 - 10);
    }

    #[test]
    fn the_tooltip_of_a_seat_names_its_job_title_host_and_state() {
        let mut p = project("falcon");
        p.seats[0].title = Some("The title".into());
        p.seats[0].host = Some("mac".into());
        p.seats[0].path = "/work/seat0".into();
        p.seats[0].status = "pending".into();
        let snapshot = Snapshot { error: None, projects: vec![p] };
        let layout = laid_out(&snapshot, &["falcon"], 60, 20);
        let tooltip = |id: &str| layout.widgets.iter().find(|w| w.id == id).and_then(|w| w.tooltip.clone());
        assert_eq!(tooltip("project-0-seat-0").unwrap(), "T-1: The title · 호스트: mac · /work/seat0 · 시작 대기");
        assert_eq!(tooltip("project-0-seat-1").unwrap(), "1 -");
        assert_eq!(tooltip("project-0-D").unwrap(), "결정 대기 1 · 답변 접수 0 · 반영 중 0 · 완료 0");
        assert_eq!(tooltip("project-0-seats").unwrap(), "좌석 접기");
        assert_eq!(tooltip("project-0-O"), None);
    }

    fn with_active(slot: &str, expanded: &[&str]) -> Layout {
        let snapshot = Snapshot { error: None, projects: vec![project("falcon")] };
        let live = Liveness::new();
        let expanded: HashSet<String> = expanded.iter().map(|s| s.to_string()).collect();
        let active = Active { project_id: "falcon".into(), slot: Some(slot.into()) };
        layout(&Facts { snapshot: &snapshot, liveness: &live, expanded: &expanded, active: Some(&active), notice: None, loaded: true }, 25, 20)
    }

    #[test]
    fn the_fold_button_names_a_hidden_seat_window_and_only_a_seat() {
        let layout = with_active("seat-3", &[]);
        let fold = layout.widgets.iter().find(|w| w.id == "project-0-seats").unwrap();
        assert_eq!(fold.tooltip.as_deref(), Some("좌석 펼치기 · 현재 창: seat 3"));
        assert!(fold.active);
        // BOARD-023: a Leader window shows on the name row, never on the fold button
        let layout = with_active("leader", &[]);
        let fold = layout.widgets.iter().find(|w| w.id == "project-0-seats").unwrap();
        assert_eq!(fold.tooltip.as_deref(), Some("좌석 펼치기"));
        assert!(!fold.active);
        assert!(layout.widgets.iter().find(|w| w.id == "project-0-name").unwrap().active);
    }

    #[test]
    fn the_name_row_carries_the_leader_time_folded_or_expanded_and_there_is_no_leader_row() {
        let snapshot = Snapshot { error: None, projects: vec![project("falcon")] };
        let name = |expanded: &[&str]| {
            let layout = laid_out(&snapshot, expanded, 40, 20);
            assert!(!layout.widgets.iter().any(|w| w.label.contains("Leader")));
            let widget = layout.widgets.iter().find(|w| w.id == "project-0-name").unwrap().clone();
            (widget.label, widget.tooltip)
        };
        for expanded in [&[][..], &["falcon"][..]] {
            let (label, tooltip) = name(expanded);
            assert_eq!(label, "falcon 10m");
            assert_eq!(tooltip.as_deref(), Some("falcon · Leader session이 게시된 뒤 지난 시간"));
        }
        let mut without = snapshot.clone();
        without.projects[0].leader = None;
        let layout = laid_out(&without, &[], 40, 20);
        let widget = layout.widgets.iter().find(|w| w.id == "project-0-name").unwrap();
        assert_eq!((widget.label.as_str(), widget.tooltip.as_deref()), ("falcon", Some("falcon")));
        let mut no_time = snapshot.clone();
        no_time.projects[0].leader = Some(Leader { elapsed: None });
        assert_eq!(laid_out(&no_time, &[], 40, 20).widgets[0].label, "falcon");
        let active = Active { project_id: "falcon".into(), slot: None };
        let live = Liveness::new();
        let none = HashSet::new();
        let marked = layout_of(&snapshot, &live, &none, Some(&active));
        assert_eq!(marked.widgets[0].label, "▶ falcon 10m");
    }

    fn layout_of(snapshot: &Snapshot, live: &Liveness, expanded: &HashSet<String>, active: Option<&Active>) -> Layout {
        layout(&Facts { snapshot, liveness: live, expanded, active, notice: None, loaded: true }, 40, 20)
    }

    #[test]
    fn nothing_is_drawn_before_the_first_read_and_an_empty_registry_says_so_after() {
        let empty = Snapshot::default();
        let live = Liveness::new();
        let expanded = HashSet::new();
        let before = layout(&Facts { snapshot: &empty, liveness: &live, expanded: &expanded, active: None, notice: None, loaded: false }, 25, 10);
        assert!(before.widgets.is_empty());
        let after = laid_out(&empty, &[], 25, 10);
        assert_eq!(after.widgets[0].lines, ["등록된 project가", "없습니다."]);
    }
}
