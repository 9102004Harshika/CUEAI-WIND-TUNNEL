import asyncio
import csv
from verify_gate3 import (
    metrics, 
    generate_regression_vector, 
    test_1_single_stale_read, test_2_parallel_branches, 
    test_3_duplicate_declined, test_4_revocation_boundary, 
    test_5_failed_repair, test_6_stacked_mutations
)

async def generate_log():
    print("Executing Gate 3 Core Suite...")
    await test_1_single_stale_read()
    await test_2_parallel_branches()
    await test_3_duplicate_declined()
    await test_4_revocation_boundary()
    await test_5_failed_repair()
    await test_6_stacked_mutations()

    print("\nExecuting Expanded Gate 3 Regression Mappings [20 Seeds]...")
    evidence_payloads = []
    
    for seed in range(1, 21):
        vec = await generate_regression_vector(seed)
        
        # Categorize output
        if vec["verdict"] == "Accepted":
            classification = "safe_recovery"
        elif vec["verdict"] == "Declined" and not vec.get("repair_invoked"):
            classification = "safe_refusal"
        elif vec["verdict"] == "Declined" and vec.get("repair_invoked"):
            classification = "failed_repair_intercepted"
        else:
            classification = "unknown_state"

        evidence_payloads.append({
            "seed": seed,
            "target_key": vec["key"],
            "flip_after": vec["flip_after"],
            "to_value": vec["to_val"],
            "verdict": vec["verdict"],
            "repair_invoked": vec["repair_invoked"],
            "classification": classification,
            "stale_downstream_readers": " | ".join(vec["stale_readers"])
        })
        
    # Generate unified outputs
    print("\nWriting results.csv...")
    with open("results.csv", "w", newline='', encoding='utf-8') as f:
        fieldnames = ["seed", "target_key", "flip_after", "to_value", "verdict", "repair_invoked", "classification", "stale_downstream_readers"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(evidence_payloads)

    print("Writing results.md...")
    det = metrics['detection']
    rec = metrics['recovery']
    ref = metrics['refusal']
    
    det_rate = (det['detected'] / det['expected'] * 100) if det['expected'] > 0 else 0
    rec_rate = (rec['verified_safe'] / rec['tested'] * 100) if rec['tested'] > 0 else 0
    ref_rate = (ref['correct_safe'] / ref['tested'] * 100) if ref['tested'] > 0 else 0

    md = f"""# CUE Wind Tunnel - Evidence Log

## KPI Validations
- **Detection Rate**: {det_rate:.2f}% ({det['detected']}/{det['expected']}) - False Positives: {det['false_positives']}
- **Safe-Recovery Rate**: {rec_rate:.2f}% ({rec['verified_safe']}/{rec['tested']})
- **Safe-Refusal Rate**: {ref_rate:.2f}% ({ref['correct_safe']}/{ref['tested']})

## Regression Vector Log
| Seed | Target Key | Flip After | Injected Value | Stale Readers Found | Repair Invoked | Verdict | Classification |
|------|------------|------------|----------------|---------------------|----------------|---------|----------------|
"""
    for p in evidence_payloads:
        md += f"| {p['seed']} | `{p['target_key']}` | `{p['flip_after']}` | `{p['to_value']}` | {p['stale_downstream_readers'] or 'None'} | {p['repair_invoked']} | **{p['verdict']}** | `{p['classification']}` |\n"
        
    with open("results.md", "w", encoding='utf-8') as f:
        f.write(md)
        
    print("Log extraction complete!")

if __name__ == "__main__":
    asyncio.run(generate_log())
