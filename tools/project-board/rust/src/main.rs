mod app;
mod data;
#[cfg(test)]
mod golden;
mod model;
mod render_cmd;
mod switch;
mod tmuxio;
mod tmuxprog;
mod ui;
mod window;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("--version") => println!("project-board-sidebar {}", env!("CARGO_PKG_VERSION")),
        Some("dump") => std::process::exit(data::dump::run(&args[1..])),
        Some("switch-project") | Some("switch-seat") => std::process::exit(switch::run(&args)),
        Some("tmux-program") => std::process::exit(tmuxprog::print()),
        Some("render") => std::process::exit(render_cmd::run(&args[1..])),
        _ => {
            let config = args.iter().position(|a| a == "--config").and_then(|i| args.get(i + 1)).cloned();
            std::process::exit(app::run(config));
        }
    }
}
