// PersonalAI desktop shell (Tauri 2). Loads the React SPA built into ../dist.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running the PersonalAI desktop shell");
}
