from models import ScenarioDef, AgentDef

SSO_SCENARIO = ScenarioDef(
    name="Acme Corp SSO Implementation",
    description="A 5-agent pipeline cooperating on implementing an SSO module, validating review and deployment invariants.",
    agents=[
        AgentDef(
            id="security",
            name="Security Agent",
            role="You are the Security Agent on a team implementing SSO for Acme Corp. You must choose ONE authentication protocol.",
            reads=[],
            writes="auth_protocol",
            allowed_values=["oauth", "saml"]
        ),
        AgentDef(
            id="engineering",
            name="Engineering Agent",
            role="You are the Engineering Agent. You've been told to implement an SSO module. The security team chose a protocol. You must confirm you'll implement it.",
            reads=["auth_protocol"],
            writes="implemented_protocol",
            allowed_values=["oauth", "saml"]
        ),
        AgentDef(
            id="qa",
            name="QA Agent",
            role="You are the QA Agent reviewing an SSO implementation. Does the implementation match the security decision?",
            reads=["auth_protocol", "implemented_protocol"],
            writes="qa_approval",
            allowed_values=["approved", "rejected"]
        ),
        AgentDef(
            id="deployment",
            name="Deployment Agent",
            role="You are the Deployment Agent. QA has reviewed the SSO module. Should we deploy?",
            reads=["qa_approval", "implemented_protocol"],
            writes="deploy_action",
            allowed_values=["deploy", "hold"]
        ),
        AgentDef(
            id="docs",
            name="Docs Agent",
            role="You are the Documentation Agent writing docs for the SSO module. What protocol are you documenting?",
            reads=["auth_protocol", "implemented_protocol"],
            writes="documented_protocol",
            allowed_values=["oauth", "saml"]
        )
    ]
)

CUSTOMER_REFUND_SCENARIO = ScenarioDef(
    name="Customer Refund Pipeline",
    description="Support decides refund or deny; finance mirrors it into the ledger; compliance approves only if they match; payout pays.",
    agents=[
        AgentDef(
            id="support",
            name="Support Agent",
            role="Decides whether customer refund is warranted.",
            reads=[],
            writes="support_decision",
            allowed_values=["refund", "deny"]
        ),
        AgentDef(
            id="finance",
            name="Finance Agent",
            role="Mirrors the support refund decision into the internal ledger.",
            reads=["support_decision"],
            writes="ledger_entry",
            allowed_values=["refund", "deny"]
        ),
        AgentDef(
            id="compliance",
            name="Compliance Agent",
            role="Approves payout only if support decision and ledger match.",
            reads=["support_decision", "ledger_entry"],
            writes="compliance_status",
            allowed_values=["approve", "reject"]
        ),
        AgentDef(
            id="payout",
            name="Payout Agent",
            role="Releases customer payout only when compliance approves.",
            reads=["compliance_status"],
            writes="payout_status",
            allowed_values=["paid", "held"]
        ),
        AgentDef(
            id="notifications",
            name="Notifications Agent",
            role="Sends customer resolution notice reflecting support decision.",
            reads=["support_decision"],
            writes="customer_notice",
            allowed_values=["refund", "deny"]
        )
    ]
)

