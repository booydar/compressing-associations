#!/usr/bin/env python3
import os
import json
import glob
from pathlib import Path

def parse_trainer_state(checkpoint_dir):
    """Parse trainer_state.json from checkpoint"""
    state_file = os.path.join(checkpoint_dir, "trainer_state.json")
    if not os.path.exists(state_file):
        return None
    
    with open(state_file, 'r') as f:
        state = json.load(f)
    
    logs = state.get("log_history", [])
    return {
        "best_metric": state.get("best_metric"),
        "best_step": state.get("best_step"),
        "global_step": state.get("global_step"),
        "logs": logs
    }

def parse_config(config_path):
    """Parse config.json to get model info"""
    if not os.path.exists(config_path):
        return {}
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    cli_args = config.get("cli_args", {})
    
    return {
        "n_layer": cli_args.get("n_layer"),
        "n_head": cli_args.get("n_head"),
        "n_embd": cli_args.get("n_embd"),
        "n_mem_tokens": cli_args.get("n_mem_tokens"),
        "base_model": cli_args.get("base_model", ""),
    }

def extract_run_info(run_dir):
    """Extract all info from a run directory"""
    parent_name = Path(run_dir).parent.name
    
    task_path = str(Path(run_dir).parent.parent)
    
    results = {
        "run_path": run_dir,
        "task": task_path.split("/")[-1],
        "model_name": parent_name,
        "config": {},
        "metrics": {}
    }
    
    config_file = os.path.join(run_dir, "config.json")
    results["config"] = parse_config(config_file)
    
    checkpoints = glob.glob(os.path.join(run_dir, "checkpoint-*"))
    if checkpoints:
        last_checkpoint = max(checkpoints, key=os.path.getctime)
        state_info = parse_trainer_state(last_checkpoint)
        
        if state_info and state_info["logs"]:
            logs = state_info["logs"]
            
            for log in logs:
                if "eval_loss" in log:
                    results["metrics"]["eval_loss"] = log.get("eval_loss")
                if "eval_exact_match" in log:
                    results["metrics"]["eval_em"] = log.get("eval_exact_match")
                if "eval_token_accuracy" in log:
                    results["metrics"]["eval_acc"] = log.get("eval_token_accuracy")
                if "loss" in log and "eval_loss" not in log:
                    results["metrics"]["train_loss"] = log.get("loss")
    
    return results

def parse_all_runs(runs_root):
    """Parse all runs from root directory"""
    all_results = []
    
    for data_path in os.listdir(runs_root):
        data_dir = os.path.join(runs_root, data_path)
        if not os.path.isdir(data_dir):
            continue
        
        for model_name in os.listdir(data_dir):
            model_dir = os.path.join(data_dir, model_name)
            if not os.path.isdir(model_dir):
                continue
            
            for run_id in os.listdir(model_dir):
                run_dir = os.path.join(model_dir, run_id)
                if not os.path.isdir(run_dir):
                    continue
                
                results = extract_run_info(run_dir)
                all_results.append(results)
    
    return all_results

def format_table(results):
    """Format results as a markdown table"""
    lines = []
    lines.append("| Task | Model | Config | Eval Loss | EM Acc | Token Acc | Train Loss |")
    lines.append("|------|-------|--------|-----------|--------|-----------|------------|")
    
    for r in results:
        task = r["task"]
        model = r["model_name"]
        cfg = r["config"]
        
        config_str = f"L{cfg.get('n_layer')}H{cfg.get('n_head')}D{cfg.get('n_embd')}"
        if cfg.get("n_mem_tokens"):
            config_str += f"_mem{cfg['n_mem_tokens']}"
        
        eval_loss = r["metrics"].get("eval_loss", "N/A")
        em_acc = r["metrics"].get("eval_em", "N/A")
        token_acc = r["metrics"].get("eval_acc", "N/A")
        train_loss = r["metrics"].get("train_loss", "N/A")
        
        def fmt(val):
            if isinstance(val, (int, float)):
                return f"{val:.4f}"
            return str(val)
        
        lines.append(f"| {task} | {model} | {config_str} | {fmt(eval_loss)} | {fmt(em_acc)} | {fmt(token_acc)} | {fmt(train_loss)} |")
    
    return "\n".join(lines)

def main():
    import sys
    
    runs_root = "./runs-test"
    if len(sys.argv) > 1:
        runs_root = sys.argv[1]
    
    print(f"Parsing runs from: {runs_root}")
    
    results = parse_all_runs(runs_root)
    
    if not results:
        print("No runs found!")
        return
    
    table = format_table(results)
    print("\n" + table)
    
    output_file = "runs_summary.md"
    with open(output_file, 'w') as f:
        f.write("# Runs Summary\n\n")
        f.write(table)
        f.write("\n\n## Detailed Results\n\n")
        for r in results:
            f.write(f"\n### {r['model_name']}\n")
            f.write(f"- Path: `{r['run_path']}`\n")
            f.write(f"- Config: {json.dumps(r['config'], indent=2)}\n")
            f.write(f"- Metrics: {json.dumps(r['metrics'], indent=2)}\n")
    
    print(f"\nSaved detailed results to: {output_file}")

if __name__ == "__main__":
    main()
