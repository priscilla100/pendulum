//! End-to-end pipeline driver.
//!
//! Given a PLTL formula on the command line, shells out to the OCaml
//! parser to obtain the AST as JSON, deserialises it, and pretty-prints
//! the result. The OCaml binary is located via:
//!
//!   1. `PLTL_PARSER_BIN` environment variable (absolute path), if set;
//!   2. otherwise, walking up from the current executable to the PLTL
//!      project root and looking for `ocaml/_build/default/main.exe`;
//!   3. otherwise, a relative fallback that works when running with
//!      `cargo run` from inside `rust/`.

use pltl_rust::Formula;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::Command;

fn find_ocaml_parser() -> PathBuf {
    if let Ok(path) = env::var("PLTL_PARSER_BIN") {
        return PathBuf::from(path);
    }
    if let Ok(exe) = env::current_exe() {
        // exe = <PLTL>/rust/target/debug/pltl_rust  →  4 ancestors up = <PLTL>
        if let Some(root) = exe.ancestors().nth(4) {
            let candidate = root.join("ocaml/_build/default/main.exe");
            if candidate.exists() {
                return candidate;
            }
        }
    }
    PathBuf::from("../ocaml/_build/default/main.exe")
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: {} '<pltl_formula>'", args[0]);
        eprintln!();
        eprintln!("Examples:");
        eprintln!("  {} 'G(p -> F q)'", args[0]);
        eprintln!("  {} 'p U q'", args[0]);
        std::process::exit(1);
    }

    let formula_str = &args[1];
    let ocaml_bin = find_ocaml_parser();
    let tmp_path = env::temp_dir().join(format!("pltl_{}.json", std::process::id()));

    println!("Input:  {}", formula_str);

    let status = Command::new(&ocaml_bin)
        .arg(formula_str)
        .arg("--json")
        .arg("--output")
        .arg(&tmp_path)
        .status()
        .map_err(|e| format!("Failed to run OCaml parser at {:?}: {}", ocaml_bin, e))?;

    if !status.success() {
        eprintln!("OCaml parser failed for formula: {}", formula_str);
        std::process::exit(1);
    }

    let json_str = fs::read_to_string(&tmp_path)?;
    let _ = fs::remove_file(&tmp_path);

    let formula: Formula = serde_json::from_str(&json_str)?;
    println!("Output: {}", formula);

    Ok(())
}
