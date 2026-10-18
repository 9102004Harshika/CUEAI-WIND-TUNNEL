import asyncio
from scenarios import SSO_SCENARIO
from pipeline import create_pipeline
from mutations import apply_mutation, Mutation, MutationType

async def main():
    m = Mutation(
        type=MutationType.CONTENT_FLIP, 
        target_agent="system",
        target_key="implemented_protocol",
        params={"from_value": "oauth", "to_value": "saml", "flip_after": "engineering"}
    )
    p = create_pipeline(scenario=SSO_SCENARIO)
    apply_mutation(p, m)
    tr = await p.run()
    
    for e in tr:
        if hasattr(e, "action_type"):
            print(f"Action: {e.agent_id} {e.action_type} - reads: {len(e.reads)}")
        else:
            print(f"Commitment: {e.agent_id} {e.key}={e.value} (v{e.version}) {e.revoked}")

if __name__ == "__main__":
    asyncio.run(main())
