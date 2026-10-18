import asyncio
from scenarios import SSO_SCENARIO
from pipeline import create_pipeline
from mutations import apply_mutation, Mutation, MutationType

async def measure_reorder_diversity():
    unique_schedules = set()
    attempts = 100
    
    for _ in range(attempts):
        m = Mutation(
            type=MutationType.REORDER,
            target_agent="qa",
            target_key="",
            params={"swap_with": "docs"}
        )
        p = create_pipeline(scenario=SSO_SCENARIO)
        apply_mutation(p, m)
        tr = await p.run()
        
        # Extract the sequence of agent executions
        schedule = tuple([e.agent_id for e in tr if hasattr(e, 'action_type') and e.action_type.startswith('execute_')])
        unique_schedules.add(schedule)
        
    print(f"Total attempts: {attempts}")
    print(f"Unique valid schedules generated: {len(unique_schedules)}")
    print("Schedules:")
    for s in unique_schedules:
        print(f" -> {', '.join(s)}")

if __name__ == "__main__":
    asyncio.run(measure_reorder_diversity())
