//! The golden screens: the cells that the Textual sidebar of 0.7.1 drew for a scene (`tests/golden/*.json`, made
//! with the 0.7.1 `SidebarApp` and `compositor.render_strips()`), against the cells `ui::paint` draws for it.
//!
//! Each file holds the scene (the facts, size, fold, active window, hover, focus and scroll) and the screen as
//! rows of runs `[text, text colour, background, bold]` with a reverse-video run already swapped. A space has no
//! text colour. The goldens of the scenes that show a Leader time were redrawn for BOARD-023 (no `Leader` row, the time on the name
//! row): each was accepted only when it equalled the 0.7.1 Textual cells apart from that change. A colour channel may differ by 1: Textual blends the text of a disabled button over the background
//! with its own rounding.
use crate::render_cmd::{self, Scene};
use crate::ui;
use ratatui::style::{Color, Modifier};
use serde_json::Value;

type Cell = (String, Option<String>, String, bool);

fn hex(color: Color) -> Option<String> {
    match color {
        Color::Rgb(r, g, b) => Some(format!("{r:02x}{g:02x}{b:02x}")),
        _ => None,
    }
}

/// The cells of the buffer as Textual's dump gives them: the reverse attribute swapped in, no text colour on a space.
fn effective(buf: &ratatui::buffer::Buffer) -> Vec<Vec<Cell>> {
    let area = *buf.area();
    let mut rows = Vec::new();
    for y in area.y..area.y + area.height {
        let mut row: Vec<Cell> = Vec::new();
        let mut x = area.x;
        while x < area.x + area.width {
            let cell = &buf[(x, y)];
            let reverse = cell.modifier.contains(Modifier::REVERSED);
            let (fg, bg) = (hex(cell.fg), hex(cell.bg).unwrap_or_default());
            let (fg, bg) = if reverse { (Some(bg), fg.unwrap_or_default()) } else { (fg, bg) };
            let symbol = cell.symbol().to_string();
            let width = ui::text_width(&symbol).max(1) as u16;
            let bold = cell.modifier.contains(Modifier::BOLD);
            if symbol == " " {
                row.push((" ".into(), None, bg, false));
            } else {
                row.push((symbol, fg, bg.clone(), bold));
                if width == 2 {
                    row.push((String::new(), None, bg, false));
                }
            }
            x += width;
        }
        rows.push(row);
    }
    rows
}

fn expand(runs: &Value) -> Vec<Vec<Cell>> {
    runs.as_array().unwrap().iter().map(|row| {
        let mut cells = Vec::new();
        for run in row.as_array().unwrap() {
            let text = run[0].as_str().unwrap();
            let fg = run[1].as_str().map(String::from);
            let bg = run[2].as_str().unwrap().to_string();
            let bold = run[3].as_bool().unwrap();
            for ch in text.chars() {
                let width = ui::text_width(&ch.to_string());
                if ch == ' ' {
                    cells.push((" ".into(), None, bg.clone(), false));
                } else {
                    cells.push((ch.to_string(), fg.clone(), bg.clone(), bold));
                    if width == 2 {
                        cells.push((String::new(), None, bg.clone(), false));
                    }
                }
            }
        }
        cells
    }).collect()
}

fn near(a: &Option<String>, b: &Option<String>) -> bool {
    match (a, b) {
        (None, None) => true,
        (Some(a), Some(b)) => (0..3).all(|i| {
            let (x, y) = (i32::from_str_radix(&a[i * 2..i * 2 + 2], 16).unwrap(), i32::from_str_radix(&b[i * 2..i * 2 + 2], 16).unwrap());
            (x - y).abs() <= 1
        }),
        _ => false,
    }
}

fn check(name: &str, text: &str) {
    let golden: Value = serde_json::from_str(text).unwrap();
    let scene: Scene = serde_json::from_value(golden["scene"].clone()).unwrap();
    let (buf, _) = render_cmd::draw(&scene);
    let drawn = effective(&buf);
    let expected = expand(&golden["expect"]);
    assert_eq!(drawn.len(), expected.len(), "{name}: rows");
    for (y, (got, want)) in drawn.iter().zip(&expected).enumerate() {
        assert_eq!(got.len(), want.len(), "{name}: cells of row {y}");
        for (x, (g, w)) in got.iter().zip(want).enumerate() {
            let same = g.0 == w.0 && near(&g.1, &w.1) && near(&Some(g.2.clone()), &Some(w.2.clone())) && g.3 == w.3;
            assert!(same, "{name}: cell ({x}, {y}) is {g:?}, Textual drew {w:?}");
        }
    }
}

macro_rules! golden {
    ($($name:ident),* $(,)?) => {
        $(
            #[test]
            fn $name() {
                check(stringify!($name), include_str!(concat!("../tests/golden/", stringify!($name), ".json")));
            }
        )*
    };
}

golden!(
    basic_folded, basic_expanded_active_seat, basic_active_leader, basic_active_slot_folded, basic_active_project,
    basic_liveness, basic_hover_name, basic_hover_count, basic_hover_fold, basic_hover_seat, basic_hover_empty_seat,
    basic_focus_decision, basic_focus_seat, basic_focus_active_seat, basic_focus_active_name, basic_wide,
    basic_narrow_scrollbar, basic_short_scrolled, long_names, long_names_scrolled_right, long_names_scrolled_end,
    many_projects, many_projects_scrolled, many_projects_expanded, counts_wide_with_scrollbar,
);
