//! `project-board-sidebar render --input SCENE.json`: draws one screen into a buffer and prints its cells as JSON
//! (`rows` of runs). The comparison with Textual's screen and the golden-screen test use this.
use crate::model::{Liveness, Snapshot};
use crate::ui::{self, Active, Facts, Interaction};
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use serde::Deserialize;
use std::collections::HashSet;

#[derive(Deserialize)]
pub struct Scene {
    pub width: u16,
    pub height: u16,
    pub snapshot: Snapshot,
    #[serde(default)]
    pub liveness: Liveness,
    #[serde(default)]
    pub expanded: Vec<String>,
    pub active: Option<Active>,
    pub hover: Option<String>,
    pub focus: Option<String>,
    #[serde(default)]
    pub scroll_x: usize,
    #[serde(default)]
    pub scroll_y: usize,
    pub tooltip: Option<(String, u16, u16)>,
}

impl<'de> Deserialize<'de> for Active {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        struct Raw {
            project_id: String,
            slot: Option<String>,
        }
        let raw = Raw::deserialize(d)?;
        Ok(Active { project_id: raw.project_id, slot: raw.slot })
    }
}

pub fn draw(scene: &Scene) -> (Buffer, ui::Layout) {
    let expanded: HashSet<String> = scene.expanded.iter().cloned().collect();
    let facts = Facts { snapshot: &scene.snapshot, liveness: &scene.liveness, expanded: &expanded, active: scene.active.as_ref(), notice: None, loaded: true };
    let layout = ui::layout(&facts, scene.width as usize, scene.height as usize);
    let (max_x, max_y) = layout.max_scroll();
    let by_id = |id: &Option<String>| id.as_ref().and_then(|id| layout.widgets.iter().find(|w| &w.id == id)).map(|w| w.key.clone());
    let interaction = Interaction {
        hover: by_id(&scene.hover),
        focus: by_id(&scene.focus),
        scroll_x: scene.scroll_x.min(max_x),
        scroll_y: scene.scroll_y.min(max_y),
    };
    let mut buf = Buffer::empty(Rect::new(0, 0, scene.width, scene.height));
    ui::paint(&mut buf, &layout, &interaction);
    if let Some((text, x, y)) = &scene.tooltip {
        ui::paint_tooltip(&mut buf, text, (*x, *y));
    }
    (buf, layout)
}

pub fn run(args: &[String]) -> i32 {
    let Some(position) = args.iter().position(|a| a == "--input") else {
        eprintln!("render: --input SCENE.json is required");
        return 2;
    };
    let text = match std::fs::read_to_string(args.get(position + 1).map(String::as_str).unwrap_or("")) {
        Ok(text) => text,
        Err(error) => {
            eprintln!("render: {error}");
            return 2;
        }
    };
    let scene: Scene = match serde_json::from_str(&text) {
        Ok(scene) => scene,
        Err(error) => {
            eprintln!("render: {error}");
            return 2;
        }
    };
    let (buf, layout) = draw(&scene);
    let rows: Vec<Vec<serde_json::Value>> = ui::runs(&buf).into_iter()
        .map(|row| row.into_iter().map(|(t, fg, bg, bold, reverse)| serde_json::json!({"t": t, "fg": fg, "bg": bg, "b": bold, "r": reverse})).collect())
        .collect();
    let geo: serde_json::Map<String, serde_json::Value> = layout.widgets.iter().filter(|w| w.button).map(|w| {
        let (x, y, width, height) = ui::screen_rect(&layout, w, (0, 0));
        (w.id.clone(), serde_json::json!([x, y - layout.top_height() as i64, width, height, w.tooltip]))
    }).collect();
    println!("{}", serde_json::json!({"w": scene.width, "h": scene.height, "rows": rows, "geo": geo, "max_scroll": layout.max_scroll(), "vbar": layout.vbar, "hbar": layout.hbar}));
    0
}
