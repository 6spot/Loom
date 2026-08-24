use loom_bench::{collect_environment, run_all_in_memory, run_all_postgres_if_available};

fn print_markdown(records: &[loom_bench::ScenarioRecord]) {
    println!(
        "| scenario | variant | dataset | wall_ms | throughput_ops/s | p50_ms | p95_ms | max_ms | cas_conflicts | discarded | reused | rows_read | notes |"
    );
    println!("|---|---|---|---|---|---|---|---|---|---|---|---|---|");
    for r in records {
        println!(
            "| {} | {} | {} | {:.2} | {:.1} | {:.2} | {:.2} | {:.2} | {} | {} | {} | {} | {} |",
            r.scenario,
            r.variant,
            r.dataset_size,
            r.wall_ms,
            r.throughput_ops_per_sec,
            r.latency.p50_ms,
            r.latency.p95_ms,
            r.latency.max_ms,
            r.cas_conflicts,
            r.discarded_cognition,
            r.reused_cognition,
            r.rows_read,
            r.notes.replace('|', "/")
        );
    }
}

#[tokio::main]
async fn main() {
    let env = collect_environment();
    println!("# Loom M11-T3 Capacity Benchmark Report");
    println!();
    println!("Environment:");
    println!("- rustc: {}", env.rustc_version);
    println!("- cargo: {}", env.cargo_version);
    println!("- git_sha: {}", env.git_sha);
    println!("- os: {}", env.os);
    println!("- cpu: {}", env.cpu_info);
    println!("- memory: {}", env.memory_kb);
    println!("- timestamp: {}", env.timestamp_utc);
    println!("- loom_version: {}", env.loom_version);
    println!();

    let mut all = run_all_in_memory().await;
    let pg = run_all_postgres_if_available().await;
    all.extend(pg);

    // Emit markdown table
    print_markdown(&all);

    // Also emit JSON for machine consumption
    println!();
    println!("JSON:");
    let json = serde_json::to_string_pretty(&all).expect("json");
    println!("{json}");

    // Write to target file for artifact
    let out_dir = std::path::Path::new("target/bench-results");
    let _ = std::fs::create_dir_all(out_dir);
    let out_path = out_dir.join("m11-t3-capacity.json");
    if let Err(e) = std::fs::write(&out_path, serde_json::to_string_pretty(&all).unwrap()) {
        eprintln!("failed to write {}: {e}", out_path.display());
    } else {
        println!("\nWrote JSON artifact to {}", out_path.display());
    }
    let md_path = out_dir.join("m11-t3-capacity.md");
    let mut md = String::new();
    md.push_str("# Loom M11-T3 Capacity Benchmark Report\n\n");
    md.push_str(&format!("- rustc: {}\n", env.rustc_version));
    md.push_str(&format!("- cargo: {}\n", env.cargo_version));
    md.push_str(&format!("- git_sha: {}\n", env.git_sha));
    md.push_str(&format!("- os: {}\n", env.os));
    md.push_str(&format!("- timestamp: {}\n", env.timestamp_utc));
    md.push_str("\n| scenario | variant | dataset | wall_ms | throughput_ops/s | p50_ms | p95_ms | max_ms | cas_conflicts | discarded | reused | rows_read | notes |\n");
    md.push_str("|---|---|---|---|---|---|---|---|---|---|---|---|---|\n");
    for r in &all {
        md.push_str(&format!(
            "| {} | {} | {} | {:.2} | {:.1} | {:.2} | {:.2} | {:.2} | {} | {} | {} | {} | {} |\n",
            r.scenario,
            r.variant,
            r.dataset_size,
            r.wall_ms,
            r.throughput_ops_per_sec,
            r.latency.p50_ms,
            r.latency.p95_ms,
            r.latency.max_ms,
            r.cas_conflicts,
            r.discarded_cognition,
            r.reused_cognition,
            r.rows_read,
            r.notes.replace('|', "/")
        ));
    }
    let _ = std::fs::write(&md_path, md);
    println!("Wrote markdown artifact to {}", md_path.display());
}
