import asyncio
import json

from models import ScenarioDef, AgentDef, Mutation, MutationType
from pipeline import create_pipeline
from invariants import check_all_invariants, get_violations
from llm_client import get_llm_client
from mutations import apply_mutation

supply_chain = ScenarioDef(
    name="Logistics Supply Chain",
    description="A multi-agent logistics operation",
    agents=[
        AgentDef(
            id="order_taker",
            name="Order Taker",
            role="You accept orders from customers.",
            reads=[],
            writes="order_status",
            allowed_values=["accepted", "rejected"]
        ),
        AgentDef(
            id="inventory",
            name="Inventory Checker",
            role="Check warehouse inventory for accepted orders.",
            reads=["order_status"],
            writes="inventory_status",
            allowed_values=["in_stock", "out_of_stock"]
        ),
        AgentDef(
            id="shipping",
            name="Shipping Agent",
            role="Ship the order if it is in stock.",
            reads=["inventory_status"],
            writes="shipping_action",
            allowed_values=["shipped", "delayed", "cancelled"]
        )
    ]
)

async def test_dynamic():
    print("Testing Generic Engine without Mutations...")
    llm = get_llm_client()
    pipeline = create_pipeline(scenario=supply_chain, llm=llm)
    trace = await pipeline.run()
    
    print("\n--- Trace ---")
    for event in trace:
        print(f"[{event.event_type.upper()}] {event}")
        
    print("\n--- Invariants ---")
    results = check_all_invariants(trace)
    for r in results:
        print(f"{'[PASS]' if r.passed else '[FAIL]'} {r.invariant_id}: {r.reason or 'OK'}")


    print("\n\nTesting Generic Engine WITH MUTATION (stale read)...")
    # In logistics:
    # 1. order_taker -> accepted
    # 2. mutant: revoke order_status!
    # 3. inventory -> checks accepted -> in_stock
    # This should fail no_downstream_disagreement. BUT wait, if we revoke BEFORE inventory reads it,
    # it fails no_action_on_revoked.
    # What if order_taker flips answer?
    
    m = Mutation(
        type=MutationType.CONTENT_FLIP,
        target_agent="order_taker",
        target_key="order_status",
        params={
            "from_value": "accepted",
            "to_value": "rejected",
            "flip_after": "inventory",
        }
    )
    
    pipeline = create_pipeline(scenario=supply_chain, llm=llm)
    apply_mutation(pipeline, m)
    trace = await pipeline.run()
    
    print("\n--- Mutant Trace ---")
    for event in trace:
        print(f"[{event.event_type.upper()}] {event}")
        
    print("\n--- Invariants ---")
    results = check_all_invariants(trace)
    for r in results:
        print(f"{'[PASS]' if r.passed else '[FAIL]'} {r.invariant_id}: {r.reason or 'OK'}")

if __name__ == "__main__":
    asyncio.run(test_dynamic())
