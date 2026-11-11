mod data;
mod model;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("--version") => println!("project-board-sidebar {}", env!("CARGO_PKG_VERSION")),
        Some("dump") => std::process::exit(data::dump::run(&args[1..])),
        _ => {
            let _ = data::Reader::new(None);
        }
    }
}
