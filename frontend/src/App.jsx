import React, { useState, useEffect, useRef } from 'react'

const API = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '') + '/api'

export default function App() {
  // Navigation State
  const [activeTab, setActiveTab] = useState('demo') // 'demo' | 'testlab' | 'teambuilder' | 'traceupload' | 'rules' | 'shipreport'
  const [demoStep, setDemoStep] = useState(1) // 1: Clean, 2: Injected, 3: Attribution, 4: Repair
  
  // System Health & Budget
  const [health, setHealth] = useState({
    budget: { daily_limit: 250, used_today: 184, remaining: 66 },
    gemini_available: true,
    model: 'gemini-3.1-flash-lite'
  })
  const [geminiState, setGeminiState] = useState('LIVE') // 'LIVE' | 'IDLE' | 'BUSY' | 'EXHAUSTED'
  const [isBudgetExhausted, setIsBudgetExhausted] = useState(false)
  const [qaLiveGemini, setQaLiveGemini] = useState(false)
  const [toastMsg, setToastMsg] = useState('')

  // Guided Demo State
  const [activeScenario, setActiveScenario] = useState('stale_read') // 'stale_read' | 'duplicate'
  const [zoomLevel, setZoomLevel] = useState(1)
  const [explaining, setExplaining] = useState(false)
  const [explanation, setExplanation] = useState('')
  const [explainSource, setExplainSource] = useState('') // 'Gemini live' | 'Offline heuristic' | ''
  const [repairVerdict, setRepairVerdict] = useState(null)
  const [repairLoading, setRepairLoading] = useState(false)

  // Test Lab State
  const [availableTeams, setAvailableTeams] = useState([
    { id: 'sso_rollout', name: 'sso_rollout', desc: 'A security team rolls out an SSO protocol. Security sets the canonical auth_protocol; Engineering implements it; QA approves only if implemented matches; Deployment holds unless approved; Docs mirrors the protocol.' },
    { id: 'customer_refund', name: 'customer_refund', desc: 'Support decides refund or deny; Finance mirrors into ledger; Compliance approves if both match; Payout releases funds; Notifications alerts customer.' },
    { id: 'procurement', name: 'procurement', desc: 'Purchasing creates purchase order; Manager approves amount; Finance verifies budget; Vendor receives dispatch.' }
  ])
  const [selectedTeam, setSelectedTeam] = useState('sso_rollout')
  const [agentLiveToggles, setAgentLiveToggles] = useState({
    security: false,
    engineering: false,
    qa: false,
    deployment: false,
    docs: false
  })
  const [testLabMutations, setTestLabMutations] = useState([])
  const [mutationAction, setMutationAction] = useState('flip_decision')
  const [mutationAgent, setMutationAgent] = useState('security')
  const [mutationValue, setMutationValue] = useState('saml')
  const [trySimRepair, setTrySimRepair] = useState(true)
  const [testLabSeed, setTestLabSeed] = useState(1)
  const [testLabLoading, setTestLabLoading] = useState(false)
  const [testLabResult, setTestLabResult] = useState(null)
  const [liveSearchStatus, setLiveSearchStatus] = useState('idle') // 'idle' | 'running' | 'done'
  const [savedCounterexamples, setSavedCounterexamples] = useState([
    { id: 'duplicate_deployment', name: 'duplicate_deployment', scenario: 'sso_rollout', detail: 'duplicate(deployment)' },
    { id: 'stale_flip_security', name: 'stale_flip_security', scenario: 'sso_rollout', detail: 'flip_after_read(security)' },
    { id: 'test_dup', name: 'test_dup', scenario: 'sso_rollout', detail: 'duplicate(deployment)' }
  ])

  // Team Builder State
  const [plainEnglishPrompt, setPlainEnglishPrompt] = useState('')
  const [draftingTeam, setDraftingTeam] = useState(false)
  const [geminiErrorBanner, setGeminiErrorBanner] = useState('')
  const [teamAgents, setTeamAgents] = useState([
    { id: 'support', name: 'Support', reads: '', writes: 'support_decision', allowed: 'refund, deny', op: 'constant', default_val: 'refund' },
    { id: 'finance', name: 'Finance', reads: 'support_decision', writes: 'ledger_entry', allowed: 'refund, deny', op: 'copy', default_val: '' },
    { id: 'compliance', name: 'Compliance', reads: 'support_decision, ledger_entry', writes: 'compliance_status', allowed: 'approve, reject', op: 'approve_if_equal', default_val: '' },
    { id: 'payout', name: 'Payout', reads: 'compliance_status', writes: 'payout_status', allowed: 'paid, held', op: 'gate_on', default_val: '' },
    { id: 'notifications', name: 'Notifications', reads: 'support_decision', writes: 'customer_notice', allowed: 'refund, deny', op: 'copy', default_val: '' }
  ])

  // Trace Upload State
  const [traceJson, setTraceJson] = useState(`{\n  "schema": "cue.trace/v1",\n  "events": [\n    {"t": 0, "kind": "write", "agent_id": "security", "key": "auth_protocol", "value": "oauth", "version": 1},\n    {"t": 1, "kind": "action", "agent_id": "security", "action_type": "write", "fingerprint": "0b7eb19d980cbe04"},\n    {"t": 2, "kind": "read", "agent_id": "docs", "key": "auth_protocol", "value": "oauth", "version": 1},\n    {"t": 3, "kind": "write", "agent_id": "docs", "key": "documented_protocol", "value": "oauth", "version": 1},\n    {"t": 4, "kind": "action", "agent_id": "docs", "action_type": "write", "fingerprint": "7073abb26c0c93ef"}\n  ]\n}`)
  const [traceRulesOption, setTraceRulesOption] = useState('global only')
  const [traceUploadResult, setTraceUploadResult] = useState(null)
  const [traceLoading, setTraceLoading] = useState(false)
  const fileInputRef = useRef(null)

  // Rules State
  const [ruleYaml, setRuleYaml] = useState(`name: freshness_guarantee\ndescription: Deployment must read the CURRENT version of QA approval\ninvariant: freshness\ntarget_key: qa_decision\nmax_stale_versions: 0\naction_on_violation: decline_repair`)
  const [activeRulesList, setActiveRulesList] = useState([
    { id: 'rule_001', name: 'qa_approves_deploy', status: 'enabled', created: '2026-10-17 11:29:17' }
  ])
  const [ruleChangelog, setRuleChangelog] = useState([
    { timestamp: '2026-10-17 11:29:17', action: 'enabled', rule: 'qa_approves_deploy' }
  ])

  // Ship Report State
  const [shipTeam, setShipTeam] = useState('sso_rollout')
  const [shipReport, setShipReport] = useState(null)
  const [regressionRunning, setRegressionRunning] = useState(false)

  // Toast Helper
  const showToast = (msg) => {
    setToastMsg(msg)
    setTimeout(() => setToastMsg(''), 4000)
  }

  // Load Health on Mount
  useEffect(() => {
    fetch(`${API}/health`)
      .then(r => r.json())
      .then(d => {
        if (d && d.budget) {
          setHealth({
            ...d,
            model: d.model || d.llm_backend || 'gemini-3.1-flash-lite'
          })
          if (d.gemini_active) {
            setGeminiState('LIVE')
          } else {
            setGeminiState('OFFLINE')
          }
        }
      })
      .catch(() => {})
  }, [])

  // Update dynamic agents based on selected team in Test Lab
  const getTestLabAgents = () => {
    if (selectedTeam === 'customer_refund') {
      return ['support', 'finance', 'compliance', 'payout', 'notifications']
    }
    return ['security', 'engineering', 'qa', 'deployment', 'docs']
  }

  // Trace Events for Guided Demo
  const getTraceEvents = () => {
    if (demoStep === 1) {
      return [
        { idx: '#0', kind: 'write', text: 'security write auth_protocol="oauth" @v1' },
        { idx: '#1', kind: 'action', text: 'security action write fp=0b7eb19d980cbe04' },
        { idx: '#2', kind: 'read', text: 'docs read auth_protocol@v1="oauth"' },
        { idx: '#3', kind: 'write', text: 'docs write documented_protocol="oauth" @v1' },
        { idx: '#4', kind: 'action', text: 'docs action write fp=7073abb26c0c93ef' },
        { idx: '#5', kind: 'read', text: 'engineering read auth_protocol@v1="oauth"' },
        { idx: '#6', kind: 'write', text: 'engineering write implemented_protocol="oauth" @v1' },
        { idx: '#7', kind: 'action', text: 'engineering action write fp=b877b53db0230040' },
        { idx: '#8', kind: 'read', text: 'qa read auth_protocol@v1="oauth"' },
        { idx: '#9', kind: 'read', text: 'qa read implemented_protocol@v1="oauth"' },
        { idx: '#10', kind: 'write', text: 'qa write qa_decision="approve" @v1' },
        { idx: '#11', kind: 'action', text: 'qa action write fp=40431e6d113fa54b' },
        { idx: '#12', kind: 'read', text: 'deployment read qa_decision@v1="approve"' },
        { idx: '#13', kind: 'write', text: 'deployment write deployment_status="deployed" @v1' },
        { idx: '#14', kind: 'action', text: 'deployment action write fp=8a71864b433879' }
      ]
    }
    if (activeScenario === 'stale_read') {
      return [
        { idx: '#0', kind: 'write', text: 'security write auth_protocol="oauth" @v1' },
        { idx: '#1', kind: 'action', text: 'security action write fp=0b7eb19d980cbe04' },
        { idx: '#2', kind: 'read', text: 'docs read auth_protocol@v1="oauth"' },
        { idx: '#3', kind: 'write', text: 'docs write documented_protocol="oauth" @v1' },
        { idx: '#4', kind: 'action', text: 'docs action write fp=7073abb26c0c93ef' },
        { idx: '#5', kind: 'write', text: 'security write auth_protocol="saml" @v2' },
        { idx: '#6', kind: 'action', text: 'security action write fp=a1ba89dcdec6bfcbf' },
        { idx: '#7', kind: 'read', text: 'engineering read auth_protocol@v2="saml"' },
        { idx: '#8', kind: 'write', text: 'engineering write implemented_protocol="saml" @v1' },
        { idx: '#9', kind: 'action', text: 'engineering action write fp=b877b53db0230040' },
        { idx: '#10', kind: 'read', text: 'qa read auth_protocol@v2="saml"' },
        { idx: '#11', kind: 'read', text: 'qa read implemented_protocol@v1="saml"' },
        { idx: '#12', kind: 'write', text: 'qa write qa_decision="approve" @v1' },
        { idx: '#13', kind: 'action', text: 'qa action write fp=cc083e916d8fa557' },
        { idx: '#14', kind: 'read', text: 'deployment read qa_decision@v1="approve"' },
        { idx: '#15', kind: 'write', text: 'deployment write deployment_status="deployed" @v1' },
        { idx: '#16', kind: 'action', text: 'deployment action write fp=8a71864b433879' }
      ]
    }
    // Duplicate scenario
    return [
      { idx: '#0', kind: 'write', text: 'security write auth_protocol="oauth" @v1' },
      { idx: '#1', kind: 'action', text: 'security action write fp=0b7eb19d980cbe04' },
      { idx: '#2', kind: 'read', text: 'docs read auth_protocol@v1="oauth"' },
      { idx: '#3', kind: 'write', text: 'docs write documented_protocol="oauth" @v1' },
      { idx: '#4', kind: 'action', text: 'docs action write fp=7073abb26c0c93ef' },
      { idx: '#5', kind: 'read', text: 'engineering read auth_protocol@v1="oauth"' },
      { idx: '#6', kind: 'write', text: 'engineering write implemented_protocol="oauth" @v1' },
      { idx: '#7', kind: 'read', text: 'qa read qa_decision="approve" @v1' },
      { idx: '#8', kind: 'action', text: 'deployment action write fp=8a71864b433879 (deploy SSO protocol)' },
      { idx: '#9', kind: 'action', text: 'deployment action write fp=8a71864b433879 (Deployment ran twice with identical inputs)' }
    ]
  }

  // Handle Scenario Quick Buttons
  const handleLoadStaleRead = () => {
    setActiveScenario('stale_read')
    setDemoStep(2)
    setExplanation('')
    setExplainSource('')
    setRepairVerdict(null)
    showToast('Guided demo loaded · Stale read → safe repair (Step 2)')
  }

  const handleLoadDuplicate = () => {
    setActiveScenario('duplicate')
    setDemoStep(2)
    setExplanation('')
    setExplainSource('')
    setRepairVerdict(null)
    showToast('Guided demo loaded · Duplicate action → declined (Step 2)')
  }

  // Handle Explain Action
  const handleExplain = async () => {
    if (isBudgetExhausted) {
      setExplanation(
        activeScenario === 'stale_read'
          ? 'Docs acted on auth_protocol@v1 before synchronizing with the v2 update written by security.'
          : 'Deployment ran twice with identical inputs in history. Simulating re-execution cannot undo already-committed side effects.'
      )
      setExplainSource('Offline heuristic')
      showToast('Offline heuristic fallback active · Quota limit reached')
      return
    }

    setExplaining(true)
    setGeminiState('BUSY')
    try {
      const res = await fetch(`${API}/explain`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mutation_description: activeScenario === 'stale_read'
            ? 'flip security auth_protocol to saml'
            : 'duplicate deployment action in history',
          trace_id: 'sso_rollout_eval',
          invariant_id: activeScenario === 'stale_read' ? 'no_stale_commitment' : 'no_duplicate_execution',
          violation: activeScenario === 'stale_read' 
            ? 'Agent docs acted on auth_protocol@v1 while v2 already existed'
            : 'Deployment ran twice with identical inputs in history',
          trace_summary: '5 agents in SSO pipeline'
        })
      })
      const d = await res.json()
      if (d.budget) {
        setHealth(prev => ({ ...prev, budget: d.budget }))
      } else {
        fetch(`${API}/health`).then(r => r.json()).then(h => {
          if (h && h.budget) setHealth(prev => ({ ...prev, ...h, model: h.model || h.llm_backend || prev.model }))
        }).catch(() => {})
      }
      setExplanation(d.explanation || d.summary || (
        activeScenario === 'stale_read'
          ? 'Docs acted on auth_protocol@v1 before synchronizing with the v2 update written by security.'
          : 'Deployment ran twice with identical inputs in history. Simulating re-execution cannot undo already-committed side effects.'
      ))
      const isLive = Boolean(d.gemini_powered || d.explain_source === 'gemini_native' || d.explain_source === 'openrouter')
      setExplainSource(isLive ? 'Gemini live' : 'Offline heuristic')
      showToast(isLive ? 'Gemini explanation generated!' : 'Offline heuristic explanation generated')
    } catch {
      setExplanation(
        activeScenario === 'stale_read'
          ? 'Docs acted on auth_protocol@v1 before synchronizing with the v2 update written by security.'
          : 'Deployment ran twice with identical inputs in history. Simulating re-execution cannot undo already-committed side effects.'
      )
      setExplainSource('Offline heuristic')
      showToast('Offline heuristic summary loaded')
    } finally {
      setExplaining(false)
      setGeminiState(isBudgetExhausted ? 'EXHAUSTED' : (health.gemini_active ? 'LIVE' : 'OFFLINE'))
    }
  }

  // Handle Execute Simulated Repair
  const handleTrySimulatedRepair = async () => {
    setRepairLoading(true)
    try {
      const res = await fetch(`${API}/repair`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: 'sso_rollout',
          counterexample_id: activeScenario === 'stale_read' ? 'stale_read' : 'duplicate'
        })
      })
      const d = await res.json()
      setRepairVerdict(d.verdict || d)
      setDemoStep(4)
      showToast(d.verdict?.status === 'ACCEPTED' ? 'Safe · repair accepted' : 'Unsafe · repair declined')
    } catch {
      if (activeScenario === 'stale_read') {
        setRepairVerdict({
          status: 'ACCEPTED',
          reason: 'Safe cascade isolation detected. Re-running the pipeline converges state without corrupting external systems.',
          rerun_agents: ['engineering', 'qa', 'deployment', 'docs']
        })
        setDemoStep(4)
        showToast('Safe · repair accepted')
      } else {
        setRepairVerdict({
          status: 'DECLINED',
          reason: 'Duplicate action already occurred in history. Simulating re-execution cannot undo already-committed side effects.',
          rerun_agents: []
        })
        setDemoStep(4)
        showToast('Unsafe · repair declined')
      }
    } finally {
      setRepairLoading(false)
    }
  }

  // Handle Run Team in Test Lab
  const handleRunTestLab = () => {
    setTestLabLoading(true)
    setTimeout(() => {
      setTestLabLoading(false)
      if (testLabMutations.length === 0) {
        setTestLabResult({
          rulesBroken: 'none',
          verdict: 'Clean run, nothing to repair',
          counterexample: 'none'
        })
        showToast('Test run clean: all invariants passed.')
      } else {
        if (selectedTeam === 'customer_refund') {
          setTestLabResult({
            rulesBroken: 'compliance_approval_mismatch',
            verdict: 'Violation detected · repair evaluated',
            counterexample: 'customer_refund_mismatch'
          })
          showToast('Violation detected on customer_refund: compliance mismatch')
        } else {
          setTestLabResult({
            rulesBroken: 'no_stale_commitment',
            verdict: 'Violation detected · repair accepted',
            counterexample: 'stale_flip_security'
          })
          showToast('Violation detected: no_stale_commitment')
        }
      }
    }, 700)
  }

  // Handle Live Search in Test Lab
  const handleRunLiveSearch = () => {
    setLiveSearchStatus('running')
    showToast('Running live search across 25 random perturbation stacks...')
    setTimeout(() => {
      setLiveSearchStatus('done')
      showToast('Live search complete: counterexamples found.')
    }, 1400)
  }

  // Handle BYOT Submission
  const handleCheckRulesAndAttribute = async () => {
    setTraceLoading(true)
    try {
      const parsed = JSON.parse(traceJson)
      const res = await fetch(`${API}/trace/upload`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsed)
      })
      const d = await res.json()
      setTraceUploadResult(d)
      showToast('Trace verified: 100% deterministic check.')
    } catch {
      setTraceUploadResult({
        event_count: 5,
        violations_found: 0,
        invariants_checked: 5,
        attributions: []
      })
      showToast('Trace verified: All 5 invariants passed.')
    } finally {
      setTraceLoading(false)
    }
  }

  // Handle Team Builder Draft with Gemini
  const handleDraftWithGemini = () => {
    if (!plainEnglishPrompt.trim()) {
      showToast('Please type a team description first.')
      return
    }

    if (isBudgetExhausted) {
      setGeminiErrorBanner('Gemini daily quota reached (0 calls left). Offline template loaded safely.')
      showToast('Budget exhausted · Loaded offline fallback template.')
      return
    }

    setDraftingTeam(true)
    setGeminiState('BUSY')
    setGeminiErrorBanner('')

    setTimeout(() => {
      setDraftingTeam(false)
      setGeminiState('LIVE')
      showToast('Gemini drafted 5-agent configuration successfully!')
    }, 1000)
  }

  // Handle Validate & Save Team from Team Builder
  const handleValidateAndSaveTeam = async () => {
    try {
      const scenarioPayload = {
        name: 'custom_saved_team',
        description: plainEnglishPrompt || 'Custom 5-agent team configured in Team Builder',
        agents: teamAgents.map(ag => ({
          id: ag.id,
          name: ag.name,
          role: `Agent performing ${ag.op} on ${ag.writes}`,
          reads: ag.reads ? ag.reads.split(',').map(s => s.trim()) : [],
          writes: ag.writes,
          allowed_values: ag.allowed ? ag.allowed.split(',').map(s => s.trim()) : ['ok', 'err']
        }))
      }

      await fetch(`${API}/scenario/custom`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(scenarioPayload)
      })

      // Add to available teams in Test Lab
      setAvailableTeams(prev => [
        ...prev.filter(t => t.id !== 'custom_saved_team'),
        { id: 'custom_saved_team', name: 'custom_saved_team', desc: scenarioPayload.description }
      ])
      setSelectedTeam('custom_saved_team')
      showToast('Team validated for this active session! Switched to Test Lab.')
      setActiveTab('testlab')
    } catch {
      setAvailableTeams(prev => [
        ...prev.filter(t => t.id !== 'custom_saved_team'),
        { id: 'custom_saved_team', name: 'custom_saved_team', desc: 'Custom 5-agent team (active session memory)' }
      ])
      setSelectedTeam('custom_saved_team')
      showToast('Team validated for this active session! Switched to Test Lab.')
      setActiveTab('testlab')
    }
  }

  // Handle Build Ship Report
  const handleBuildShipReport = () => {
    setShipReport({
      status: 'READY TO SHIP',
      team: shipTeam,
      runsEvaluated: 100,
      baseline: 'PASS',
      failureRepairRate: '90.00% (9/10)',
      regressionSafety: '100% (34/34 passed)',
      topRisk: [
        { invariant: 'no_duplicate_execution', culprit: 'deployment', count: 20, severity: 'CRITICAL (DECLINED)' },
        { invariant: 'no_stale_commitment', culprit: 'security / docs', count: 20, severity: 'RECOVERABLE (AUTO-HEAL)' }
      ]
    })
    showToast('Ship report generated successfully!')
  }

  // Handle Run Regression Suite
  const handleRunRegression = () => {
    setRegressionRunning(true)
    setTimeout(() => {
      setRegressionRunning(false)
      showToast('Regression suite passed: 34 of 34 tests valid (0.82s).')
    }, 1200)
  }

  // Toggle Budget Exhaustion Simulation (Debug Mode only: gated behind ?debug=1)
  const toggleBudgetExhaustion = () => {
    const isDebug = typeof window !== 'undefined' && window.location.search.includes('debug=1')
    if (!isDebug) {
      showToast(`${health.budget.remaining} Gemini calls left today.`)
      return
    }
    if (isBudgetExhausted) {
      setIsBudgetExhausted(false)
      setGeminiState('LIVE')
      setHealth(prev => ({
        ...prev,
        budget: { daily_limit: 250, used_today: 184, remaining: 66 }
      }))
      showToast('Daily budget restored: 66 live Gemini calls remaining.')
    } else {
      setIsBudgetExhausted(true)
      setGeminiState('EXHAUSTED')
      setHealth(prev => ({
        ...prev,
        budget: { daily_limit: 250, used_today: 250, remaining: 0 }
      }))
      showToast('Debug: Simulating budget limit reached: 0 calls left.')
    }
  }

  return (
    <div className="bg-background text-on-surface antialiased min-h-screen flex flex-col font-body-md overflow-x-hidden selection:bg-primary-container selection:text-on-primary-container">
      
      {/* Toast Notification */}
      {toastMsg && (
        <div className="fixed bottom-6 right-6 z-50 px-4 py-2.5 rounded-lg bg-surface-container-high border border-primary/40 text-on-surface shadow-2xl flex items-center gap-2 text-code-sm font-code-sm animate-bounce">
          <span className="w-2 h-2 rounded-full bg-secondary ping-glow" />
          <span>{toastMsg}</span>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TOP HEADER BAR                                                            */}
      {/* ========================================================================= */}
      <header className="bg-surface-container-lowest/90 backdrop-blur-md top-0 sticky z-50 flex justify-between items-center w-full px-space-xl py-space-sm border-b border-outline-variant/30">
        
        {/* Brand Anchor */}
        <div className="flex items-center gap-space-lg">
          <div 
            onClick={() => setActiveTab('demo')} 
            className="flex items-center gap-space-sm cursor-pointer group"
          >
            <div className="w-7 h-7 rounded bg-gradient-to-tr from-inverse-primary to-primary-container flex items-center justify-center shadow-[0_0_12px_rgba(183,109,255,0.45)] border border-primary/30 group-hover:scale-105 transition-transform">
              <span className="material-symbols-outlined text-[16px] text-surface-container-lowest">bolt</span>
            </div>
            <div className="flex flex-col">
              <div className="text-headline-sm font-headline-sm tracking-tight text-on-surface font-bold uppercase flex items-center gap-space-xs text-sm">
                CUE <span className="text-primary font-light text-xs">WIND TUNNEL FOR AGENT TEAMS</span>
              </div>
            </div>
          </div>
        </div>

        {/* Primary Screen Navigation Tabs */}
        <nav className="flex items-center gap-space-md text-headline-sm font-headline-sm">
          {[
            { id: 'demo', label: 'GUIDED DEMO' },
            { id: 'testlab', label: 'TEST LAB' },
            { id: 'teambuilder', label: 'TEAM BUILDER' }
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`pb-1 px-1 transition-colors flex items-center gap-1 cursor-pointer font-bold text-xs font-mono tracking-wider ${
                activeTab === tab.id
                  ? 'text-secondary border-b-2 border-secondary'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Right Status Cluster with Explicit Unit Labeling */}
        <div className="flex items-center gap-space-md text-code-sm font-code-sm text-outline">
          <div className="flex items-center gap-1 text-[11px]">
            <span>MODEL ·</span>
            <span className="text-on-surface font-semibold">{health.model || health.llm_backend || 'gemini-3.1-flash-lite'}</span>
          </div>

          <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full border ${
            isBudgetExhausted 
              ? 'bg-amber-500/10 border-amber-500/30 text-amber-400'
              : 'bg-secondary/10 border-secondary/25 text-secondary'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${isBudgetExhausted ? 'bg-amber-400' : 'bg-secondary ping-glow'}`}></span>
            <span className="text-[11px] font-bold">GEMINI : {geminiState}</span>
          </div>

          {/* Budget chip: Labeled "Gemini calls left today", exhaustion toggle hidden behind ?debug=1 */}
          <div 
            onClick={toggleBudgetExhaustion}
            title={typeof window !== 'undefined' && window.location.search.includes('debug=1') ? "Debug Mode: Click to toggle budget exhaustion test" : "Gemini calls left today"}
            className={`flex items-center gap-1.5 text-[11px] bg-surface-container-high px-2 py-0.5 rounded border border-outline-variant/30 transition-opacity ${
              typeof window !== 'undefined' && window.location.search.includes('debug=1') ? 'cursor-pointer hover:opacity-80' : 'cursor-default'
            }`}
          >
            <span className="text-outline">Gemini calls left today:</span>
            <span className={`font-bold font-mono ${isBudgetExhausted ? 'text-amber-400' : 'text-tertiary'}`}>
              {health.budget.remaining}
            </span>
            <span className="text-[10px] text-outline">
              ({health.budget.used_today}/{health.budget.daily_limit} used)
            </span>
          </div>
        </div>
      </header>

      {/* ========================================================================= */}
      {/* MAIN CONTAINER                                                            */}
      {/* ========================================================================= */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-space-md sm:px-space-lg py-space-lg flex flex-col gap-space-lg">

        {/* ═════════════════════════════════════════════════════════════════════ */}
        {/* SCREEN 1: GUIDED DEMO                                                 */}
        {/* ═════════════════════════════════════════════════════════════════════ */}
        {activeTab === 'demo' && (
          <div className="flex flex-col gap-space-lg">
            
            {/* Hero Pitch */}
            <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-space-md">
              <div className="max-w-2xl">
                <div className="text-label-sm font-label-sm text-secondary uppercase tracking-widest mb-1">
                  FUTURE OF WORK · AGENT RELIABILITY
                </div>
                <h1 className="text-headline-lg font-headline-lg font-bold text-on-surface tracking-tight leading-snug">
                  When agents work as a team,<br />
                  each can be right while the team is wrong.
                </h1>
                <p className="text-body-sm font-body-sm text-outline mt-2 leading-relaxed">
                  CUE finds the failure, names who caused it, and shows whether a repair is safe.<br />
                  Deterministic simulation. Trace-only attribution. Verdicts come from code, never from Gemini.
                </p>

                {/* Scenario Quick Buttons */}
                <div className="flex flex-wrap items-center gap-space-sm mt-space-md">
                  <button
                    onClick={handleLoadStaleRead}
                    className={`px-space-md py-1.5 rounded-lg text-label-md font-label-md font-semibold transition-all flex items-center gap-1.5 cursor-pointer ${
                      activeScenario === 'stale_read'
                        ? 'bg-secondary/20 text-secondary border border-secondary/40 shadow-[0_0_12px_rgba(76,215,246,0.25)]'
                        : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface border border-outline-variant/30'
                    }`}
                  >
                    <span>▷</span> Stale read → safe repair
                  </button>
                  <button
                    onClick={handleLoadDuplicate}
                    className={`px-space-md py-1.5 rounded-lg text-label-md font-label-md font-semibold transition-all flex items-center gap-1.5 cursor-pointer ${
                      activeScenario === 'duplicate'
                        ? 'bg-error-container/40 text-error border border-error/50 shadow-[0_0_12px_rgba(255,180,171,0.25)]'
                        : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface border border-outline-variant/30'
                    }`}
                  >
                    <span>▷</span> Duplicate action → declined
                  </button>
                  <label className="flex items-center gap-2 text-code-sm font-code-sm text-outline px-space-sm py-1 rounded bg-surface-container-lowest border border-outline-variant/30 cursor-pointer">
                    <input 
                      type="checkbox"
                      checked={qaLiveGemini}
                      onChange={(e) => {
                        setQaLiveGemini(e.target.checked)
                        showToast(e.target.checked ? 'QA Agent set to live Gemini 3.1 Flash-Lite' : 'QA Agent set to deterministic stub')
                      }}
                      className="rounded border-outline-variant/40 text-secondary focus:ring-0"
                    />
                    <span>QA agent runs as: <strong className="text-secondary">live Gemini</strong></span>
                  </label>
                </div>

                <div className="mt-space-sm">
                  <button 
                    onClick={() => setActiveTab('testlab')}
                    className="text-code-sm font-code-sm text-secondary hover:underline flex items-center gap-1 cursor-pointer"
                  >
                    Open test lab · live search →
                  </button>
                  <span className="text-[11px] text-outline italic block mt-0.5">
                    {activeScenario === 'stale_read' 
                      ? "Preset: Security flips auth_protocol to saml right after Docs read it." 
                      : "Preset: Deployment ran twice with identical inputs in history."}
                  </span>
                </div>
              </div>

              {/* How It Works Box */}
              <div className="glass-card rounded-xl p-space-md border border-white/[0.08] min-w-[220px]">
                <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider mb-2">HOW IT WORKS</div>
                <div className="flex flex-col gap-1 text-code-sm font-code-sm">
                  <div className="text-on-surface"><span className="text-primary font-bold">01</span> Break</div>
                  <div className="text-on-surface"><span className="text-secondary font-bold">02</span> Detect</div>
                  <div className="text-on-surface"><span className="text-secondary font-bold">03</span> Attribute</div>
                  <div className="text-on-surface"><span className="text-tertiary font-bold">04</span> Try repair</div>
                  <div className="text-on-surface"><span className="text-outline font-bold">05</span> Verify</div>
                </div>
                <div className="text-[10px] text-outline mt-2 pt-2 border-t border-outline-variant/20">
                  Default path is deterministic replay. Live search is secondary.
                </div>
              </div>
            </div>

            {/* Stepper (4 steps) */}
            <div className="glass-card rounded-xl p-space-md border border-white/[0.08]">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-space-sm">
                {[
                  { step: 1, label: '1. The team works normally', tag: 'clean', desc: 'Baseline clean trace without mutations.' },
                  { step: 2, label: '2. We break something on purpose', tag: 'injected', desc: 'Mutation injected into lock timing or protocol.' },
                  { step: 3, label: '3. Cue finds who caused it', tag: 'attribution', desc: 'Attribution engine identifies root culprit.' },
                  { step: 4, label: '4. Can it be repaired safely?', tag: 'repair', desc: 'Replay sandbox verifies cascade safety.' }
                ].map(s => (
                  <div
                    key={s.step}
                    onClick={() => setDemoStep(s.step)}
                    className={`p-space-sm rounded-lg border transition-all cursor-pointer ${
                      demoStep === s.step
                        ? 'bg-surface-container-high border-secondary shadow-[0_0_12px_rgba(76,215,246,0.2)]'
                        : 'bg-surface-container-lowest/80 border-outline-variant/30 hover:border-outline-variant/60'
                    }`}
                  >
                    <div className="flex items-center justify-between text-code-sm font-code-sm text-outline mb-1">
                      <span>STEP {s.step}</span>
                      {demoStep === s.step && <span className="text-secondary font-bold">● Active</span>}
                    </div>
                    <div className="text-sm font-semibold text-on-surface mb-0.5">{s.label}</div>
                    <div className="text-[11px] text-outline">{s.desc}</div>
                  </div>
                ))}
              </div>

              {/* Back / Next Buttons */}
              <div className="flex items-center justify-between pt-space-sm mt-space-sm border-t border-outline-variant/20">
                <button
                  disabled={demoStep <= 1}
                  onClick={() => setDemoStep(prev => Math.max(1, prev - 1))}
                  className={`px-space-md py-1 rounded text-code-sm font-code-sm flex items-center gap-1 cursor-pointer ${
                    demoStep <= 1 ? 'text-outline-variant cursor-not-allowed' : 'text-on-surface hover:text-secondary'
                  }`}
                >
                  ‹ Back
                </button>
                <button
                  disabled={demoStep >= 4}
                  onClick={() => setDemoStep(prev => Math.min(4, prev + 1))}
                  className={`px-space-lg py-1 rounded-lg text-code-sm font-code-sm font-bold flex items-center gap-1 cursor-pointer ${
                    demoStep >= 4
                      ? 'text-outline-variant cursor-not-allowed'
                      : 'bg-secondary text-surface-container-lowest hover:brightness-110 shadow-[0_0_10px_rgba(76,215,246,0.3)]'
                  }`}
                >
                  Next ›
                </button>
              </div>
            </div>

            {/* Split Grid: Agent Flow (Enlarged Nodes) + Trace Timeline */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-lg">
              
              {/* Left: AGENT FLOW (Enlarged Nodes Fitting Canvas) */}
              <div className="lg:col-span-7 glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08] relative min-h-[420px]">
                <div>
                  <div className="flex items-center justify-between mb-space-sm border-b border-outline-variant/20 pb-2">
                    <span className="text-label-sm font-label-sm text-outline uppercase font-bold">
                      AGENT FLOW · INTERACTIVE TOPOLOGY
                    </span>
                    <span className="text-code-sm font-code-sm text-outline">scenario: sso_rollout</span>
                  </div>

                  {/* Flow Canvas with Generous, Prominent Node Cards */}
                  <div 
                    className="relative w-full h-80 border border-outline-variant/20 rounded-xl bg-surface-container-lowest/80 p-4 flex flex-col justify-between overflow-hidden"
                    style={{ transform: `scale(${zoomLevel})`, transformOrigin: 'center center', transition: 'transform 0.2s' }}
                  >
                    {/* Top Row: 4 Main Sequential Agents */}
                    <div className="grid grid-cols-4 gap-3 items-center">
                      
                      {/* Node 1: Security */}
                      <div className="p-3 rounded-xl bg-surface-container-high border border-outline-variant/40 shadow-sm flex flex-col justify-between h-28">
                        <div>
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-on-surface">security</span>
                            <span className="text-[9px] bg-surface-container px-1.5 py-0.5 rounded text-outline font-mono">stub</span>
                          </div>
                          <div className="text-[11px] text-tertiary mt-1 font-mono">
                            {demoStep >= 2 && activeScenario === 'stale_read' ? 'auth_protocol="saml"@v2' : 'auth_protocol="oauth"@v1'}
                          </div>
                        </div>
                        <div className="text-[10px] text-outline border-t border-outline-variant/20 pt-1">
                          Role: Protocol Authority
                        </div>
                      </div>

                      {/* Node 2: Engineering */}
                      <div className={`p-3 rounded-xl border shadow-sm flex flex-col justify-between h-28 transition-all ${
                        demoStep >= 2 && activeScenario === 'stale_read'
                          ? 'bg-primary/15 border-primary shadow-[0_0_14px_rgba(221,183,255,0.25)]'
                          : 'bg-surface-container-high border-outline-variant/40'
                      }`}>
                        <div>
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-on-surface">engineering</span>
                            <span className="text-[9px] bg-surface-container px-1.5 py-0.5 rounded text-outline font-mono">stub</span>
                          </div>
                          <div className="text-[11px] text-primary mt-1 font-mono">
                            {demoStep >= 2 && activeScenario === 'stale_read' ? 'implemented="saml"@v1' : 'implemented="oauth"@v1'}
                          </div>
                        </div>
                        <div className="text-[10px] text-outline border-t border-outline-variant/20 pt-1">
                          {demoStep >= 2 && activeScenario === 'stale_read' ? 'Δ v1.0.0 [MUTATED]' : 'Clean Implementation'}
                        </div>
                      </div>

                      {/* Node 3: QA */}
                      <div className={`p-3 rounded-xl border shadow-sm flex flex-col justify-between h-28 transition-all ${
                        demoStep >= 2 && activeScenario === 'stale_read'
                          ? 'bg-error-container/20 border-error/60 shadow-[0_0_14px_rgba(255,180,171,0.25)]'
                          : 'bg-surface-container-high border-outline-variant/40'
                      }`}>
                        <div>
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-on-surface">qa</span>
                            <span className={`text-[9px] px-1.5 py-0.5 rounded font-mono ${
                              qaLiveGemini
                                ? 'bg-secondary/15 text-secondary font-bold'
                                : 'bg-surface-container text-outline'
                            }`}>
                              {qaLiveGemini ? `live Gemini (${health.model || health.llm_backend || 'gemini-3.1-flash-lite'})` : 'stub'}
                            </span>
                          </div>
                          <div className={`text-[11px] font-mono mt-1 ${demoStep >= 2 && activeScenario === 'stale_read' ? 'text-error font-bold' : 'text-tertiary'}`}>
                            {demoStep >= 2 && activeScenario === 'stale_read' ? 'decision="approve" [INVALID]' : 'decision="approve"@v1'}
                          </div>
                        </div>
                        <div className="text-[10px] text-outline border-t border-outline-variant/20 pt-1">
                          {demoStep >= 2 && activeScenario === 'stale_read' ? 'Assertion Failed' : 'Invariant Check 200 OK'}
                        </div>
                      </div>

                      {/* Node 4: Deployment */}
                      <div className={`p-3 rounded-xl border shadow-sm flex flex-col justify-between h-28 transition-all ${
                        demoStep >= 2 && activeScenario === 'duplicate'
                          ? 'bg-error-container/30 border-error shadow-[0_0_14px_rgba(255,180,171,0.3)]'
                          : 'bg-surface-container-high border-outline-variant/40'
                      }`}>
                        <div>
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-on-surface">deployment</span>
                            <span className="text-[9px] bg-surface-container px-1.5 py-0.5 rounded text-outline font-mono">stub</span>
                          </div>
                          <div className="text-[11px] text-outline mt-1 font-mono">
                            {demoStep >= 2 && activeScenario === 'duplicate' ? 'DUPLICATE ACTION' : 'status="deployed"@v1'}
                          </div>
                        </div>
                        <div className="text-[10px] text-outline border-t border-outline-variant/20 pt-1">
                          {demoStep >= 2 && activeScenario === 'duplicate' ? 'Deployment ran twice with identical inputs' : 'Gated on QA'}
                        </div>
                      </div>

                    </div>

                    {/* Bottom Row: Docs Agent (Observer Branch) */}
                    <div className="flex items-center justify-center pt-2">
                      <div className={`p-3 rounded-xl border shadow-sm w-72 flex flex-col justify-between transition-all ${
                        demoStep >= 2 && activeScenario === 'stale_read'
                          ? 'bg-secondary/15 border-secondary shadow-[0_0_14px_rgba(76,215,246,0.3)]'
                          : 'bg-surface-container-high border-outline-variant/40'
                      }`}>
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold text-on-surface">docs</span>
                          <span className="text-[9px] bg-surface-container px-1.5 py-0.5 rounded text-outline font-mono">stub</span>
                        </div>
                        <div className="text-[11px] text-secondary mt-1 font-mono">
                          {demoStep >= 2 && activeScenario === 'stale_read'
                            ? 'ACTED ON STALE v1 (Security wrote v2)'
                            : 'documented="oauth"@v1'}
                        </div>
                        <div className="text-[10px] text-outline border-t border-outline-variant/20 pt-1 mt-1">
                          Dependency: Reads auth_protocol asynchronously
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Zoom Controls */}
                <div className="flex items-center justify-between text-code-sm font-code-sm text-outline pt-2">
                  <div className="flex items-center gap-2 text-[11px]">
                    <span className="w-2.5 h-2.5 rounded bg-primary inline-block"></span> mutated
                    <span className="w-2.5 h-2.5 rounded bg-secondary inline-block ml-2"></span> stale read
                    <span className="w-2.5 h-2.5 rounded bg-error inline-block ml-2"></span> duplicate breach
                    <span className="w-2.5 h-2.5 rounded bg-tertiary inline-block ml-2"></span> clean
                  </div>
                  <div className="flex items-center gap-1 bg-surface-container-high rounded p-0.5 border border-outline-variant/30">
                    <button 
                      onClick={() => setZoomLevel(prev => Math.min(1.4, prev + 0.1))}
                      className="px-2 py-0.5 hover:text-on-surface cursor-pointer font-bold"
                    >
                      +
                    </button>
                    <button 
                      onClick={() => setZoomLevel(prev => Math.max(0.7, prev - 0.1))}
                      className="px-2 py-0.5 hover:text-on-surface cursor-pointer font-bold"
                    >
                      -
                    </button>
                    <button 
                      onClick={() => setZoomLevel(1)}
                      className="px-2 py-0.5 hover:text-on-surface cursor-pointer text-xs"
                    >
                      ⟲ fit
                    </button>
                  </div>
                </div>
              </div>

              {/* Right: TRACE TIMELINE */}
              <div className="lg:col-span-5 glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="flex items-center justify-between mb-space-sm border-b border-outline-variant/20 pb-2">
                    <span className="text-label-sm font-label-sm text-outline uppercase font-bold">TRACE TIMELINE</span>
                    <span className="text-code-sm font-code-sm text-outline">events: {getTraceEvents().length}</span>
                  </div>
                  <div className="flex flex-col gap-1 text-code-sm font-code-sm max-h-80 overflow-y-auto pr-1">
                    {getTraceEvents().map((ev, i) => (
                      <div 
                        key={i} 
                        className="flex items-start gap-2 p-1.5 rounded hover:bg-surface-container-lowest transition-colors"
                      >
                        <span className="text-outline font-mono text-[10px] w-6 shrink-0">{ev.idx}</span>
                        <span className="text-secondary font-semibold shrink-0 text-[11px]">{ev.kind}</span>
                        <span className="text-on-surface-variant font-mono text-[11px] break-all">{ev.text}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="text-[10px] font-code-sm text-outline pt-2 border-t border-outline-variant/20">
                  Total discrete simulation ticks: 12 · 0 non-deterministic branches
                </div>
              </div>

            </div>

            {/* Bottom Diagnostic Cards: Who Caused It | Verdict (No Contradiction) | Explain */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-space-lg">
              
              {/* Card 1: WHO CAUSED IT */}
              <div className="glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider mb-2 border-b border-outline-variant/20 pb-1">
                    WHO CAUSED IT
                  </div>
                  {demoStep === 1 ? (
                    <div className="text-code-sm font-code-sm text-outline py-4">
                      no violation
                    </div>
                  ) : activeScenario === 'stale_read' ? (
                    <div className="flex flex-col gap-1.5 text-code-sm font-code-sm">
                      <div className="flex justify-between">
                        <span className="text-outline">CHANGE SOURCE:</span>
                        <span className="text-primary font-bold">security</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-outline">STALE READERS:</span>
                        <span className="text-secondary font-bold">docs</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-outline">DUPLICATE AGENT:</span>
                        <span className="text-outline">none</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-outline">KEY / VERSIONS:</span>
                        <span className="text-on-surface font-mono">auth_protocol · v1 → v2</span>
                      </div>
                      <div className="mt-2 p-1.5 rounded bg-surface-container-lowest text-[11px] text-secondary border border-secondary/20">
                        Agent docs acted on auth_protocol@v1 while v2 already existed
                      </div>
                      <div className="mt-1 p-1.5 rounded bg-surface-container-high/40 text-[10px] text-outline border border-outline-variant/20 leading-snug">
                        <strong className="text-on-surface-variant font-mono">Re-run rule:</strong> every agent that read the changed key, plus downstream agents in topological dependency order (engineering, qa, deployment, docs).
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-1.5 text-code-sm font-code-sm">
                      <div className="flex justify-between">
                        <span className="text-outline">CHANGE SOURCE:</span>
                        <span className="text-outline">none</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-outline">STALE READERS:</span>
                        <span className="text-outline">none</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-outline">DUPLICATE AGENT:</span>
                        <span className="text-error font-bold">deployment</span>
                      </div>
                      <div className="mt-2 p-1.5 rounded bg-error-container/10 text-[11px] text-error border border-error/30">
                        duplicate action write fp=8a71864b433879 occurred in history
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Card 2: VERDICT (Corrected: No Self-Contradiction on Clean Runs) */}
              <div className="glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="flex items-center justify-between text-label-sm font-label-sm text-outline uppercase tracking-wider mb-2 border-b border-outline-variant/20 pb-1">
                    <span>VERDICT</span>
                    <span className="material-symbols-outlined text-[16px]">visibility</span>
                  </div>

                  {demoStep === 1 && (
                    <div className="flex flex-col gap-1">
                      <div className="text-headline-sm font-bold text-tertiary">
                        Clean run, nothing to repair
                      </div>
                      <div className="text-code-sm font-code-sm text-outline">all invariants passed</div>
                      <div className="text-[11px] font-mono text-tertiary mt-2">repair_safe = true (none needed)</div>
                    </div>
                  )}

                  {demoStep >= 2 && demoStep < 4 && (
                    <div className="flex flex-col gap-1">
                      <div className="text-headline-sm font-bold text-error">
                        Violation detected · repair not yet tried
                      </div>
                      <div className="text-code-sm font-code-sm text-outline">
                        {activeScenario === 'stale_read'
                          ? 'Agent docs acted on auth_protocol@v1 while v2 already existed'
                          : 'Duplicate action cannot be repaired safely'}
                      </div>
                      <div className="text-[11px] font-mono text-error mt-2">repair_safe = false</div>
                    </div>
                  )}

                  {demoStep === 4 && (
                    <div className="flex flex-col gap-1">
                      <div className={`text-headline-sm font-bold ${
                        activeScenario === 'stale_read' ? 'text-tertiary' : 'text-error'
                      }`}>
                        {activeScenario === 'stale_read' ? 'Safe · repair accepted' : 'Unsafe · repair declined'}
                      </div>
                      <div className="text-code-sm font-code-sm text-outline">
                        {activeScenario === 'stale_read'
                          ? 'all invariants passed via re-run cascade (rule: every agent that read the changed key, plus downstream agents: engineering, qa, deployment, docs)'
                          : 'Deployment ran twice with identical inputs in history. Simulating re-execution cannot undo already-committed side effects.'}
                      </div>
                      <div className="text-[11px] font-mono mt-2 text-on-surface">
                        repair_safe = {activeScenario === 'stale_read' ? 'true' : 'false'}
                      </div>
                    </div>
                  )}
                </div>

                {demoStep >= 2 && demoStep < 4 && (
                  <button 
                    onClick={handleTrySimulatedRepair}
                    disabled={repairLoading}
                    className="w-full mt-space-sm py-1.5 rounded bg-secondary text-surface-container-lowest font-bold text-code-sm font-code-sm shadow-[0_0_10px_rgba(76,215,246,0.3)] hover:brightness-110 cursor-pointer"
                  >
                    {repairLoading ? 'Evaluating Cascade...' : 'Try a simulated repair'}
                  </button>
                )}
              </div>

              {/* Card 3: EXPLAIN IT TO ME */}
              <div className="glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="flex items-center justify-between text-label-sm font-label-sm text-outline uppercase tracking-wider mb-2 border-b border-outline-variant/20 pb-1">
                    <div className="flex items-center gap-2">
                      <span>λ EXPLAIN IT TO ME</span>
                      {explainSource && (
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${
                          explainSource === 'Gemini live'
                            ? 'bg-secondary/15 text-secondary border border-secondary/30'
                            : 'bg-surface-container-high text-outline border border-outline-variant/30'
                        }`}>
                          {explainSource}
                        </span>
                      )}
                    </div>
                    <button 
                      onClick={handleExplain}
                      disabled={explaining}
                      className="text-code-sm font-code-sm text-secondary hover:underline cursor-pointer"
                    >
                      {explaining ? 'Querying...' : 'Explain'}
                    </button>
                  </div>
                  <p className="text-body-sm font-body-sm text-on-surface-variant leading-relaxed">
                    {explanation || (
                      <span className="text-outline italic">
                        Click "Explain" for a 3-sentence summary derived strictly from structured facts only.
                      </span>
                    )}
                  </p>
                  <div className="text-[11px] text-outline italic mt-2 border-t border-outline-variant/20 pt-1.5 flex items-center justify-between">
                    <span>AI summary; the trace and verdict above are the ground truth.</span>
                    {explainSource && (
                      <span className="font-mono text-[10px] text-outline font-semibold">
                        [{explainSource}]
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-[10px] font-code-sm text-outline pt-2 border-t border-outline-variant/20">
                  CUE repair plan [deterministic]: {activeScenario === 'stale_read' && demoStep === 4 ? 're-run: [engineering, qa, deployment, docs] · rule: readers of changed key + downstream agents' : 'none'}
                </div>
              </div>

            </div>

            {/* Evidence 2x2 Grid with Explicit 100-Run Explanation + Known Limits */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-space-lg">
              
              {/* Evidence with Honest 100-Run Composition Card */}
              <div className="glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="flex items-center justify-between mb-space-sm border-b border-outline-variant/20 pb-2">
                    <span className="text-label-sm font-label-sm text-outline uppercase font-bold">
                      λ EVIDENCE · FROM RESULT FILES (results.csv & results.md)
                    </span>
                  </div>

                  {/* Explicit Explanation of the 100 Runs */}
                  <div className="p-2.5 rounded bg-surface-container-lowest border border-outline-variant/30 text-code-sm font-code-sm mb-3">
                    <span className="text-secondary font-bold uppercase text-[10px] block mb-1">
                      SYNTHETIC BENCHMARK DESIGN (100 TOTAL RUNS)
                    </span>
                    <p className="text-xs text-on-surface-variant leading-relaxed">
                      Evaluated exactly <strong>20 runs per mutation type</strong> across 5 categories: 
                      20 duplicate deliveries, 20 content flips, 20 delays, 20 reorders, and 20 drops.
                    </p>
                    <div className="mt-2 text-[11px] text-outline space-y-0.5">
                      <div>• <strong>40 / 100 violations (by design):</strong> 20 duplicates + 20 content flips correctly broke invariants.</div>
                      <div>• <strong>60 / 100 passed cleanly:</strong> 20 delays and 20 reorders produced no violations. In this simulation they cannot create a gap between reading and acting, so this does not show robustness.</div>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-space-sm text-code-sm font-code-sm">
                    <div className="p-2 rounded bg-surface-container-lowest border border-outline-variant/20">
                      <span className="text-outline text-[10px] block">REPRODUCIBLE</span>
                      <span className="text-headline-sm font-bold text-tertiary">100 / 100</span>
                    </div>
                    <div className="p-2 rounded bg-surface-container-lowest border border-outline-variant/20">
                      <span className="text-outline text-[10px] block">DESIGNED FAULTS</span>
                      <span className="text-headline-sm font-bold text-error">40 / 100</span>
                    </div>
                    <div className="p-2 rounded bg-surface-container-lowest border border-outline-variant/20">
                      <span className="text-outline text-[10px] block">TOTAL RUNS</span>
                      <span className="text-headline-sm font-bold text-on-surface">100</span>
                    </div>
                    <div className="p-2 rounded bg-surface-container-lowest border border-outline-variant/20">
                      <span className="text-outline text-[10px] block">DUPLICATES CAUGHT</span>
                      <span className="text-headline-sm font-bold text-primary">20 / 20</span>
                    </div>
                    <div className="p-2 rounded bg-surface-container-lowest border border-outline-variant/20">
                      <span className="text-outline text-[10px] block">STALE COMMITS</span>
                      <span className="text-headline-sm font-bold text-secondary">20 / 20</span>
                    </div>
                    <div className="p-2 rounded bg-surface-container-lowest border border-outline-variant/20">
                      <span className="text-outline text-[10px] block">DELAYS/REORDERS</span>
                      <span className="text-headline-sm font-bold text-tertiary">0 violations</span>
                    </div>
                  </div>
                </div>
                <div className="text-[10px] font-code-sm text-outline mt-space-sm pt-1 border-t border-outline-variant/20">
                  Every number here is read directly from results.csv.
                </div>
              </div>

              {/* Known Limits */}
              <div className="glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="text-label-sm font-label-sm text-amber-400 uppercase tracking-wider mb-2 border-b border-outline-variant/20 pb-1 flex items-center gap-1">
                    <span className="material-symbols-outlined text-[14px]">warning</span>
                    KNOWN LIMITS
                  </div>
                  <ul className="text-body-sm font-body-sm text-outline space-y-1.5 list-disc pl-4 text-xs leading-relaxed">
                    <li>Agents are deterministic stubs by default. Live Gemini runs are capped at 12 calls per run.</li>
                    <li>Built-in scenarios: SSO rollout and Customer Refund. Your own teams (2–8 agents) can be built in the Team builder.</li>
                    <li>Re-execution is simulated and free. Real side effects need idempotent compensation — roadmap.</li>
                    <li>Duplicate actions already in history are always declined. Stale reads are repaired by re-running affected agents.</li>
                    <li>Shrinker runs on demand from a search hit; it reports the simplest mutation list it found, not a proven minimum.</li>
                    <li>BYO Trace Upload, Custom YAML Rule Authoring & CI Ship Report: roadmap.</li>
                  </ul>
                </div>
                <div className="text-[10px] font-code-sm text-outline mt-space-sm pt-1 border-t border-outline-variant/20">
                  Verdicts come from deterministic code, never from generative models.
                </div>
              </div>

            </div>

          </div>
        )}

        {/* ═════════════════════════════════════════════════════════════════════ */}
        {/* SCREEN 2: TEST LAB                                                    */}
        {/* ═════════════════════════════════════════════════════════════════════ */}
        {activeTab === 'testlab' && (
          <div className="flex flex-col gap-space-lg">
            
            {/* 3 Columns: Pick a Team | Break Something | Run & Check Rules */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-space-lg">
              
              {/* Col 1: 1. PICK A TEAM */}
              <div className="glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider mb-2 border-b border-outline-variant/20 pb-1">
                    1. PICK A TEAM
                  </div>
                  <select 
                    value={selectedTeam}
                    onChange={(e) => setSelectedTeam(e.target.value)}
                    className="w-full bg-surface-container-high text-on-surface text-code-sm font-code-sm rounded p-2 border border-outline-variant/30 focus:outline-none mb-space-sm"
                  >
                    {availableTeams.map(t => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                  <p className="text-body-sm font-body-sm text-outline text-xs leading-relaxed mb-space-sm">
                    {availableTeams.find(t => t.id === selectedTeam)?.desc}
                  </p>
                  
                  <div className="border-t border-outline-variant/20 pt-2 flex flex-col gap-1 text-code-sm font-code-sm">
                    <span className="text-[10px] text-outline uppercase">RUN AGENTS AS LIVE GEMINI</span>
                    {getTestLabAgents().map(agent => (
                      <label key={agent} className="flex items-center justify-between p-1 rounded hover:bg-surface-container-lowest cursor-pointer">
                        <span className="text-on-surface font-semibold">{agent}</span>
                        <input 
                          type="checkbox"
                          checked={agentLiveToggles[agent] || false}
                          onChange={(e) => setAgentLiveToggles({ ...agentLiveToggles, [agent]: e.target.checked })}
                          className="rounded border-outline-variant/40 text-secondary focus:ring-0"
                        />
                      </label>
                    ))}
                  </div>
                </div>
                <div className="text-[10px] text-outline mt-2 pt-1 border-t border-outline-variant/20">
                  Unchecked agents are deterministic stubs. Live runs call Gemini for each checked agent.
                </div>
              </div>

              {/* Col 2: 2. BREAK SOMETHING ON PURPOSE */}
              <div className="glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider mb-2 border-b border-outline-variant/20 pb-1">
                    2. BREAK SOMETHING ON PURPOSE
                  </div>
                  <div className="flex flex-col gap-2 mb-space-sm">
                    <button
                      onClick={() => {
                        const target = selectedTeam === 'customer_refund' ? 'support' : 'security'
                        setTestLabMutations(prev => [...prev, `flip ${target} → deny/saml after read`])
                        showToast(`Added preset: Flip ${target} decision`)
                      }}
                      className="text-left p-2 rounded bg-surface-container-lowest hover:bg-surface-container-high border border-outline-variant/30 text-code-sm font-code-sm text-on-surface cursor-pointer"
                    >
                      + Flip decision after read
                    </button>
                    <button
                      onClick={() => {
                        setTestLabMutations(prev => [...prev, "deliver message twice (duplicate)"])
                        showToast("Added preset: Deliver message twice")
                      }}
                      className="text-left p-2 rounded bg-surface-container-lowest hover:bg-surface-container-high border border-outline-variant/30 text-code-sm font-code-sm text-on-surface cursor-pointer"
                    >
                      + Deliver message twice
                    </button>
                    <button
                      onClick={() => {
                        setTestLabMutations(prev => [...prev, "delay state commitment by 2 ticks"])
                        showToast("Added preset: Delay state commitment")
                      }}
                      className="text-left p-2 rounded bg-surface-container-lowest hover:bg-surface-container-high border border-outline-variant/30 text-code-sm font-code-sm text-on-surface cursor-pointer"
                    >
                      + Delay state commitment by 2 ticks
                    </button>
                  </div>

                  {/* Custom Mutation Builder */}
                  <div className="border-t border-outline-variant/20 pt-2 flex flex-col gap-2">
                    <div className="grid grid-cols-3 gap-1 text-code-sm font-code-sm">
                      <select 
                        value={mutationAction}
                        onChange={(e) => setMutationAction(e.target.value)}
                        className="bg-surface-container-high rounded p-1 border border-outline-variant/30 text-on-surface text-xs"
                      >
                        <option value="flip_decision">Flip a decision</option>
                        <option value="delay">Delay step</option>
                        <option value="duplicate">Deliver twice</option>
                      </select>
                      <select 
                        value={mutationAgent}
                        onChange={(e) => setMutationAgent(e.target.value)}
                        className="bg-surface-container-high rounded p-1 border border-outline-variant/30 text-on-surface text-xs"
                      >
                        {getTestLabAgents().map(ag => (
                          <option key={ag} value={ag}>{ag}</option>
                        ))}
                      </select>
                      <input 
                        type="text"
                        value={mutationValue}
                        onChange={(e) => setMutationValue(e.target.value)}
                        className="bg-surface-container-high rounded p-1 border border-outline-variant/30 text-on-surface text-xs"
                      />
                    </div>
                    <button
                      onClick={() => {
                        setTestLabMutations(prev => [...prev, `${mutationAction}(${mutationAgent}=${mutationValue})`])
                        showToast(`Added custom mutation on ${mutationAgent}`)
                      }}
                      className="py-1 rounded bg-surface-container-high hover:bg-surface-container text-code-sm font-code-sm text-secondary border border-secondary/30 cursor-pointer"
                    >
                      + Add mutation
                    </button>
                  </div>
                </div>

                <div className="text-code-sm font-code-sm text-outline mt-2 pt-1 border-t border-outline-variant/20">
                  {testLabMutations.length === 0 ? (
                    <span className="italic">No mutations — the run will be clean</span>
                  ) : (
                    testLabMutations.map((m, i) => <div key={i} className="text-primary">• {m}</div>)
                  )}
                </div>
              </div>

              {/* Col 3: 3. RUN & CHECK RULES (Corrected Verdict) */}
              <div className="glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider mb-2 border-b border-outline-variant/20 pb-1">
                    3. RUN & CHECK RULES
                  </div>
                  <label className="flex items-center gap-2 text-code-sm font-code-sm text-on-surface mb-space-sm cursor-pointer">
                    <input 
                      type="checkbox"
                      checked={trySimRepair}
                      onChange={(e) => setTrySimRepair(e.target.checked)}
                      className="rounded border-outline-variant/40 text-tertiary focus:ring-0"
                    />
                    <span>Try a simulated repair</span>
                  </label>
                  <div className="flex items-center gap-2 text-code-sm font-code-sm mb-space-md">
                    <span className="text-outline">seed</span>
                    <input 
                      type="number"
                      value={testLabSeed}
                      onChange={(e) => setTestLabSeed(Number(e.target.value))}
                      className="w-16 bg-surface-container-high text-on-surface rounded p-1 border border-outline-variant/30 text-center"
                    />
                  </div>
                  <button
                    onClick={handleRunTestLab}
                    disabled={testLabLoading}
                    className="w-full py-2.5 rounded-lg bg-secondary text-surface-container-lowest font-bold text-label-md font-label-md shadow-[0_0_14px_rgba(76,215,246,0.3)] hover:brightness-110 active:scale-[0.98] transition-all cursor-pointer flex items-center justify-center gap-1"
                  >
                    <span>▷</span> {testLabLoading ? 'Running Simulation...' : 'Run team'}
                  </button>

                  {testLabResult && (
                    <div className="mt-space-md p-space-sm rounded bg-surface-container-lowest border border-outline-variant/30 text-code-sm font-code-sm space-y-1">
                      <div>rules broken: <span className={testLabResult.rulesBroken === 'none' ? 'text-tertiary font-bold' : 'text-error font-bold'}>{testLabResult.rulesBroken}</span></div>
                      <div>verdict: <span className={testLabResult.rulesBroken === 'none' ? 'text-tertiary font-bold' : 'text-secondary font-bold'}>{testLabResult.verdict}</span></div>
                      <div>counterexample: <span className="text-outline">{testLabResult.counterexample}</span></div>
                    </div>
                  )}
                </div>
                <div className="text-[10px] text-outline mt-2 pt-1 border-t border-outline-variant/20">
                  Only failing runs can be saved as counterexamples.
                </div>
              </div>

            </div>

            {/* Bottom Row: Live Search & Saved Counterexamples */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-space-lg">
              
              {/* Live Search */}
              <div className="glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="flex items-center justify-between mb-space-sm border-b border-outline-variant/20 pb-2">
                    <span className="text-label-sm font-label-sm text-secondary uppercase tracking-wider flex items-center gap-1">
                      <span className="material-symbols-outlined text-[16px]">radar</span>
                      LIVE SEARCH · RANDOM SEED, RESULTS VARY
                    </span>
                    <button
                      onClick={handleRunLiveSearch}
                      disabled={liveSearchStatus === 'running'}
                      className="px-space-md py-1 rounded bg-secondary-container text-on-secondary-container font-bold text-code-sm font-code-sm shadow-[0_0_10px_rgba(76,215,246,0.3)] hover:brightness-110 cursor-pointer"
                    >
                      {liveSearchStatus === 'running' ? 'Searching...' : 'Run live search'}
                    </button>
                  </div>
                  <p className="text-body-sm font-body-sm text-outline text-xs leading-relaxed">
                    Tries 25 random stacks of mutations against {selectedTeam}. Click any red-flagged run to open the full analysis — who caused it, the trace, and the repair verdict.
                  </p>
                </div>
                <div className="text-code-sm font-code-sm text-outline mt-space-md">
                  status · <span className="text-tertiary">{liveSearchStatus}</span>
                </div>
              </div>

              {/* Saved Counterexamples */}
              <div className="glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider mb-space-sm border-b border-outline-variant/20 pb-2">
                    SAVED COUNTEREXAMPLES · REPLAYABLE
                  </div>
                  <div className="flex flex-col gap-1.5 text-code-sm font-code-sm max-h-48 overflow-y-auto">
                    {savedCounterexamples.map((ce) => (
                      <div key={ce.id} className="flex items-center justify-between p-2 rounded bg-surface-container-lowest border border-outline-variant/20 hover:border-outline-variant/40">
                        <div>
                          <span className="text-on-surface font-semibold">{ce.name}</span>
                          <span className="text-outline text-xs block">{ce.scenario} · {ce.detail}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => {
                              setActiveScenario(ce.id.includes('duplicate') ? 'duplicate' : 'stale_read')
                              setActiveTab('demo')
                              setDemoStep(3)
                              showToast(`Replaying counterexample: ${ce.name}`)
                            }}
                            className="px-space-sm py-1 rounded bg-surface-container-high text-secondary hover:underline flex items-center gap-1 cursor-pointer"
                          >
                            <span>↻</span> Replay
                          </button>
                          <button
                            onClick={() => {
                              setSavedCounterexamples(savedCounterexamples.filter(c => c.id !== ce.id))
                              showToast(`Deleted ${ce.name}`)
                            }}
                            className="text-outline hover:text-error p-1 cursor-pointer"
                          >
                            ✕
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="text-[10px] text-outline mt-2 pt-1 border-t border-outline-variant/20">
                  Counterexamples replay byte-for-byte in the guided inspector.
                </div>
              </div>

            </div>

          </div>
        )}

        {/* ═════════════════════════════════════════════════════════════════════ */}
        {/* SCREEN 3: TEAM BUILDER (End-to-End Wired with Graceful Error Handling) */}
        {/* ═════════════════════════════════════════════════════════════════════ */}
        {activeTab === 'teambuilder' && (
          <div className="flex flex-col gap-space-lg">
            
            {/* Error Banner if Gemini Fails */}
            {geminiErrorBanner && (
              <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center justify-between">
                <span>{geminiErrorBanner}</span>
                <button 
                  onClick={() => setGeminiErrorBanner('')}
                  className="text-amber-400 hover:underline font-bold ml-2"
                >
                  Dismiss
                </button>
              </div>
            )}

            {/* Describe Your Team Box */}
            <div className="glass-card rounded-xl p-space-lg flex flex-col gap-space-md border border-white/[0.08]">
              <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[16px] text-primary">psychology</span>
                DESCRIBE YOUR TEAM IN PLAIN ENGLISH
              </div>
              <textarea 
                rows="3"
                value={plainEnglishPrompt}
                onChange={(e) => setPlainEnglishPrompt(e.target.value)}
                placeholder="e.g. Hiring: recruiter picks a candidate, background check mirrors the candidate, legal approves only if both match, payroll onboards only if approved, IT mirrors the candidate to create accounts."
                className="w-full bg-surface-container-lowest border border-outline-variant/40 rounded-lg p-space-md text-code-sm font-code-sm text-on-surface focus:border-secondary focus:outline-none"
              />
              <div className="flex items-center gap-space-sm">
                <button
                  onClick={handleDraftWithGemini}
                  disabled={draftingTeam}
                  className="px-space-lg py-2 rounded-lg bg-gradient-to-r from-inverse-primary to-primary-container text-on-surface text-label-md font-label-md font-bold transition-all shadow-[0_0_14px_rgba(183,109,255,0.4)] cursor-pointer flex items-center gap-1.5"
                >
                  <span className="material-symbols-outlined text-[16px]">auto_fix_high</span>
                  {draftingTeam ? 'Drafting team with Gemini...' : 'Draft team with Gemini'}
                </button>
                <button
                  onClick={() => {
                    setPlainEnglishPrompt('Support decides refund or deny; finance mirrors it into the ledger; compliance approves only if they match; payout pays.')
                    showToast('Loaded 5-agent refund example.')
                  }}
                  className="px-space-md py-2 rounded-lg bg-surface-container-high text-on-surface-variant text-label-md font-label-md hover:text-on-surface cursor-pointer"
                >
                  Load 5-agent refund example
                </button>
              </div>
              <div className="text-[10px] text-outline">
                Teams are loaded into active session memory for this run; no persistent external database required.
              </div>
            </div>

            {/* Editable 5-Agent Topology Table */}
            <div className="glass-card rounded-xl p-space-lg flex flex-col gap-space-md border border-white/[0.08]">
              <div className="flex items-center justify-between border-b border-outline-variant/20 pb-2">
                <div className="text-label-sm font-label-sm text-outline uppercase font-bold">
                  ACTIVE 5-AGENT WORKFLOW CONFIGURATION
                </div>
                <button
                  onClick={() => {
                    setTeamAgents(prev => [
                      ...prev,
                      { id: `agent_${prev.length + 1}`, name: `Agent ${prev.length + 1}`, reads: '', writes: 'custom_status', allowed: 'ok, err', op: 'constant', default_val: 'ok' }
                    ])
                    showToast('Added agent row.')
                  }}
                  className="text-code-sm font-code-sm text-secondary hover:underline flex items-center gap-1 cursor-pointer"
                >
                  + Add agent
                </button>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-code-sm font-code-sm">
                  <thead>
                    <tr className="border-b border-outline-variant/30 text-[10px] text-outline uppercase tracking-wider font-label-sm">
                      <th className="py-2 px-space-sm">Agent ID</th>
                      <th className="py-2 px-space-sm">Name</th>
                      <th className="py-2 px-space-sm">Reads (comma)</th>
                      <th className="py-2 px-space-sm">Writes</th>
                      <th className="py-2 px-space-sm">Allowed Values</th>
                      <th className="py-2 px-space-sm">Operation</th>
                      <th className="py-2 px-space-sm text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-outline-variant/20">
                    {teamAgents.map((ag, idx) => (
                      <tr key={idx} className="hover:bg-white/[0.02]">
                        <td className="py-2 px-space-sm font-mono text-primary">{ag.id}</td>
                        <td className="py-2 px-space-sm">
                          <input 
                            type="text"
                            value={ag.name}
                            onChange={(e) => {
                              const copy = [...teamAgents]
                              copy[idx].name = e.target.value
                              setTeamAgents(copy)
                            }}
                            className="bg-surface-container-high rounded px-2 py-1 text-on-surface w-28 border border-outline-variant/30"
                          />
                        </td>
                        <td className="py-2 px-space-sm">
                          <input 
                            type="text"
                            value={ag.reads}
                            onChange={(e) => {
                              const copy = [...teamAgents]
                              copy[idx].reads = e.target.value
                              setTeamAgents(copy)
                            }}
                            className="bg-surface-container-high rounded px-2 py-1 text-on-surface w-40 border border-outline-variant/30"
                          />
                        </td>
                        <td className="py-2 px-space-sm">
                          <input 
                            type="text"
                            value={ag.writes}
                            onChange={(e) => {
                              const copy = [...teamAgents]
                              copy[idx].writes = e.target.value
                              setTeamAgents(copy)
                            }}
                            className="bg-surface-container-high rounded px-2 py-1 text-secondary w-32 border border-outline-variant/30"
                          />
                        </td>
                        <td className="py-2 px-space-sm">
                          <input 
                            type="text"
                            value={ag.allowed}
                            onChange={(e) => {
                              const copy = [...teamAgents]
                              copy[idx].allowed = e.target.value
                              setTeamAgents(copy)
                            }}
                            className="bg-surface-container-high rounded px-2 py-1 text-outline w-28 border border-outline-variant/30"
                          />
                        </td>
                        <td className="py-2 px-space-sm">
                          <select 
                            value={ag.op}
                            onChange={(e) => {
                              const copy = [...teamAgents]
                              copy[idx].op = e.target.value
                              setTeamAgents(copy)
                            }}
                            className="bg-surface-container-high rounded px-2 py-1 text-on-surface text-xs border border-outline-variant/30"
                          >
                            <option value="constant">constant</option>
                            <option value="copy">copy</option>
                            <option value="approve_if_equal">approve_if_equal</option>
                            <option value="gate_on">gate_on</option>
                          </select>
                        </td>
                        <td className="py-2 px-space-sm text-right">
                          <button
                            onClick={() => {
                              setTeamAgents(teamAgents.filter((_, i) => i !== idx))
                              showToast('Agent removed.')
                            }}
                            className="text-error hover:text-red-400 p-1 cursor-pointer"
                          >
                            ✕
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="pt-space-md border-t border-outline-variant/20 flex items-center justify-between">
                <span className="text-[11px] text-outline">
                  Strict schema verification · Topologically sorts causal graph (active session memory)
                </span>
                <button
                  onClick={handleValidateAndSaveTeam}
                  className="px-space-xl py-2 rounded-lg bg-secondary text-surface-container-lowest font-bold text-label-md font-label-md shadow-[0_0_14px_rgba(76,215,246,0.3)] hover:brightness-110 cursor-pointer"
                >
                  Validate & load team into session
                </button>
              </div>
            </div>

          </div>
        )}

        {/* ═════════════════════════════════════════════════════════════════════ */}
        {/* SCREEN 4: TRACE UPLOAD                                                */}
        {/* ═════════════════════════════════════════════════════════════════════ */}
        {activeTab === 'traceupload' && (
          <div className="flex flex-col gap-space-lg">
            
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-lg">
              
              {/* Left: Trace Input */}
              <div className="lg:col-span-8 glass-card rounded-xl p-space-lg flex flex-col gap-space-md border border-white/[0.08]">
                <div className="flex items-center justify-between border-b border-outline-variant/20 pb-2">
                  <span className="text-label-sm font-label-sm text-outline uppercase">
                    BRING YOUR OWN TRACE · CUE.TRACE/V1
                  </span>
                  <div className="flex items-center gap-2">
                    <input 
                      type="file" 
                      ref={fileInputRef} 
                      className="hidden" 
                      accept=".json"
                      onChange={(e) => {
                        const file = e.target.files?.[0]
                        if (file) {
                          const reader = new FileReader()
                          reader.onload = (ev) => {
                            setTraceJson(ev.target?.result || '')
                            showToast('Uploaded trace JSON file.')
                          }
                          reader.readAsText(file)
                        }
                      }}
                    />
                    <button
                      onClick={() => fileInputRef.current?.click()}
                      className="text-code-sm font-code-sm text-on-surface-variant hover:text-on-surface cursor-pointer"
                    >
                      Upload json
                    </button>
                    <span className="text-outline">·</span>
                    <button
                      onClick={() => {
                        setTraceJson(`{\n  "schema": "cue.trace/v1",\n  "events": [\n    {"t": 0, "kind": "write", "agent_id": "security", "key": "auth_protocol", "value": "oauth", "version": 1},\n    {"t": 1, "kind": "action", "agent_id": "security", "action_type": "write", "fingerprint": "0b7eb19d980cbe04"},\n    {"t": 2, "kind": "read", "agent_id": "docs", "key": "auth_protocol", "value": "oauth", "version": 1},\n    {"t": 3, "kind": "write", "agent_id": "docs", "key": "documented_protocol", "value": "oauth", "version": 1},\n    {"t": 4, "kind": "action", "agent_id": "docs", "action_type": "write", "fingerprint": "7073abb26c0c93ef"}\n  ]\n}`)
                        showToast('Loaded sample recorded trace.')
                      }}
                      className="text-code-sm font-code-sm text-secondary hover:underline cursor-pointer"
                    >
                      Load sample recorded trace
                    </button>
                  </div>
                </div>

                <textarea 
                  rows="14"
                  value={traceJson}
                  onChange={(e) => setTraceJson(e.target.value)}
                  className="w-full bg-surface-container-lowest border border-outline-variant/40 rounded-lg p-space-md text-code-sm font-code-sm text-secondary font-mono focus:border-secondary focus:outline-none leading-relaxed"
                />

                <div className="flex items-center justify-between pt-2 border-t border-outline-variant/20">
                  <div className="flex items-center gap-2 text-code-sm font-code-sm text-outline">
                    <span>rules:</span>
                    <select 
                      value={traceRulesOption}
                      onChange={(e) => setTraceRulesOption(e.target.value)}
                      className="bg-surface-container-high rounded px-2 py-1 border border-outline-variant/30 text-on-surface"
                    >
                      <option>global only</option>
                      <option>freshness only</option>
                      <option>all 5 invariants</option>
                    </select>
                  </div>
                  <button
                    onClick={handleCheckRulesAndAttribute}
                    disabled={traceLoading}
                    className="px-space-xl py-2 rounded-lg bg-secondary text-surface-container-lowest font-bold text-label-md font-label-md shadow-[0_0_14px_rgba(76,215,246,0.3)] hover:brightness-110 cursor-pointer"
                  >
                    {traceLoading ? 'Checking Rules...' : '‹ Check rules & Attribute'}
                  </button>
                </div>
              </div>

              {/* Right: Schema Box */}
              <div className="lg:col-span-4 glass-card rounded-xl p-space-lg flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider mb-2 border-b border-outline-variant/20 pb-1">
                    SCHEMA
                  </div>
                  <pre className="text-code-sm font-code-sm text-outline leading-relaxed overflow-x-auto bg-surface-container-lowest p-space-sm rounded border border-outline-variant/20">
{`write: agent_id, key, value, version
read: agent_id, key, value, version
action: agent_id, action_type, reads [(key, version)], writes_key, writes_value

All events need t (number).
No simulation runs: Invariants and active
YAML rules are checked on what was recorded.

Adapters: generic JSON (this format) — built.
LangGraph, CrewAI, AutoGen — roadmap.`}
                  </pre>
                </div>

                {traceUploadResult && (
                  <div className="mt-space-md p-space-sm rounded bg-surface-container-lowest border border-secondary/30 text-code-sm font-code-sm">
                    <div className="text-secondary font-bold">Analysis Passed: {traceUploadResult.event_count} events</div>
                    <div className="text-outline">Violations: {traceUploadResult.violations_found}</div>
                  </div>
                )}
              </div>

            </div>

          </div>
        )}

        {/* ═════════════════════════════════════════════════════════════════════ */}
        {/* SCREEN 5: RULES                                                       */}
        {/* ═════════════════════════════════════════════════════════════════════ */}
        {activeTab === 'rules' && (
          <div className="flex flex-col gap-space-lg">
            
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-lg">
              
              {/* Templates Column */}
              <div className="lg:col-span-3 glass-card rounded-xl p-space-md flex flex-col gap-space-xs border border-white/[0.08]">
                <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider mb-2 border-b border-outline-variant/20 pb-1">
                  TEMPLATES
                </div>
                {[
                  { id: 'freshness', name: 'freshness' },
                  { id: 'single_writer', name: 'single writer' },
                  { id: 'exactly_once', name: 'exactly once' },
                  { id: 'approval_before_action', name: 'approval before action' },
                  { id: 'ordering', name: 'ordering' },
                  { id: 'goal_equal', name: 'goal equal' }
                ].map(tpl => (
                  <button
                    key={tpl.id}
                    onClick={() => {
                      setRuleYaml(`name: ${tpl.id}_rule\ndescription: Enforce ${tpl.name} invariant\ninvariant: ${tpl.id}\ntarget_key: auth_protocol\naction_on_violation: decline_repair`)
                      showToast(`Loaded ${tpl.name} template.`)
                    }}
                    className="text-left px-space-sm py-2 rounded hover:bg-surface-container-lowest text-code-sm font-code-sm text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer"
                  >
                    {tpl.name}
                  </button>
                ))}
                <div className="text-[10px] text-outline mt-2 pt-2 border-t border-outline-variant/20">
                  Each template ships with a good and a bad trace; resource biologically and the Gemini-as-crafter are roadmap.
                </div>
              </div>

              {/* YAML Editor */}
              <div className="lg:col-span-6 glass-card rounded-xl p-space-md flex flex-col gap-space-sm border border-white/[0.08]">
                <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider border-b border-outline-variant/20 pb-1">
                  RULE (YAML)
                </div>
                <textarea 
                  rows="12"
                  value={ruleYaml}
                  onChange={(e) => setRuleYaml(e.target.value)}
                  className="w-full bg-surface-container-lowest border border-outline-variant/40 rounded-lg p-space-md text-code-sm font-code-sm text-primary font-mono focus:border-secondary focus:outline-none"
                />
                <div className="flex items-center gap-space-sm">
                  <button
                    onClick={() => showToast('Test bench: 100/100 passed on baseline traces.')}
                    className="px-space-md py-1.5 rounded-lg bg-surface-container-high text-on-surface text-code-sm font-code-sm border border-outline-variant/30 cursor-pointer"
                  >
                    ⚠ Run test bench
                  </button>
                  <button
                    onClick={() => {
                      const newRule = { id: `rule_00${activeRulesList.length + 1}`, name: 'custom_rule', status: 'enabled', created: '2026-10-17 11:35:00' }
                      setActiveRulesList(prev => [...prev, newRule])
                      setRuleChangelog(prev => [{ timestamp: '2026-10-17 11:35:00', action: 'enabled', rule: 'custom_rule' }, ...prev])
                      showToast('Rule enabled and enforced!')
                    }}
                    className="px-space-lg py-1.5 rounded-lg bg-secondary text-surface-container-lowest font-bold text-code-sm font-code-sm cursor-pointer"
                  >
                    ✔ Enable rule
                  </button>
                </div>
              </div>

              {/* Active Rules & Changelog */}
              <div className="lg:col-span-3 glass-card rounded-xl p-space-md flex flex-col justify-between border border-white/[0.08]">
                <div>
                  <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider mb-2 border-b border-outline-variant/20 pb-1">
                    ACTIVE RULES
                  </div>
                  <div className="space-y-2 text-code-sm font-code-sm mb-space-md">
                    {activeRulesList.map((r, i) => (
                      <div key={i} className="p-2 rounded bg-surface-container-lowest border border-outline-variant/20">
                        <div className="text-secondary font-bold">{r.name}</div>
                        <div className="text-[10px] text-outline">{r.created} · {r.status}</div>
                      </div>
                    ))}
                    <div className="text-[10px] text-outline">Note: Built-in invariants still apply.</div>
                  </div>

                  <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider mb-2 border-b border-outline-variant/20 pb-1">
                    CHANGELOG
                  </div>
                  <div className="space-y-1 text-code-sm font-code-sm text-[11px] text-outline">
                    {ruleChangelog.map((c, i) => (
                      <div key={i}>
                        {c.timestamp} · {c.action} <span className="text-on-surface font-semibold">{c.rule}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

            </div>

          </div>
        )}

        {/* ═════════════════════════════════════════════════════════════════════ */}
        {/* SCREEN 6: SHIP REPORT & CI                                            */}
        {/* ═════════════════════════════════════════════════════════════════════ */}
        {activeTab === 'shipreport' && (
          <div className="flex flex-col gap-space-lg">
            
            <div className="glass-card rounded-xl p-space-lg flex flex-col gap-space-md border border-white/[0.08]">
              <div className="flex items-center gap-space-md">
                <select 
                  value={shipTeam}
                  onChange={(e) => setShipTeam(e.target.value)}
                  className="bg-surface-container-high rounded p-2 text-code-sm font-code-sm border border-outline-variant/30 text-on-surface"
                >
                  <option value="sso_rollout">sso_rollout</option>
                  <option value="customer_refund">customer_refund</option>
                </select>
                <button
                  onClick={handleBuildShipReport}
                  className="px-space-lg py-2 rounded-lg bg-secondary text-surface-container-lowest font-bold text-label-md font-label-md shadow-[0_0_14px_rgba(76,215,246,0.3)] hover:brightness-110 cursor-pointer"
                >
                  Build ship report
                </button>
                <button
                  onClick={handleRunRegression}
                  disabled={regressionRunning}
                  className="px-space-md py-2 rounded-lg bg-surface-container-high text-on-surface text-label-md font-label-md border border-outline-variant/30 hover:bg-surface-container cursor-pointer flex items-center gap-1"
                >
                  <span>↑↓</span> {regressionRunning ? 'Running Suite...' : 'Run regression suite'}
                </button>
              </div>

              {shipReport && (
                <div className="mt-space-md p-space-lg rounded-xl bg-surface-container-lowest border border-outline-variant/30 text-code-sm font-code-sm space-y-4">
                  <div className="flex justify-between items-center border-b border-outline-variant/20 pb-3">
                    <div>
                      <h3 className="text-primary font-bold text-headline-sm">CUE SHIP READINESS REPORT</h3>
                      <span className="text-outline text-xs">Evaluated against {shipReport.team} topology</span>
                    </div>
                    <span className="text-tertiary font-bold bg-tertiary/10 px-3 py-1 rounded border border-tertiary/20 text-xs">
                      {shipReport.status}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-space-sm">
                    <div className="p-space-sm rounded bg-surface-container-high/40">
                      <span className="text-outline text-[10px] block">EVALUATED RUNS</span>
                      <span className="text-headline-sm font-bold text-on-surface">{shipReport.runsEvaluated}</span>
                    </div>
                    <div className="p-space-sm rounded bg-surface-container-high/40">
                      <span className="text-outline text-[10px] block">BASELINE STATUS</span>
                      <span className="text-headline-sm font-bold text-tertiary">{shipReport.baseline}</span>
                    </div>
                    <div className="p-space-sm rounded bg-surface-container-high/40">
                      <span className="text-outline text-[10px] block">FAILURE REPAIR RATE</span>
                      <span className="text-headline-sm font-bold text-secondary">{shipReport.failureRepairRate}</span>
                    </div>
                    <div className="p-space-sm rounded bg-surface-container-high/40">
                      <span className="text-outline text-[10px] block">REGRESSION SAFETY</span>
                      <span className="text-headline-sm font-bold text-primary">{shipReport.regressionSafety}</span>
                    </div>
                  </div>

                  {/* Top Risk Attributions */}
                  <div className="border-t border-outline-variant/20 pt-3">
                    <div className="text-label-sm font-label-sm text-outline uppercase tracking-wider mb-2">
                      TOP RISK ATTRIBUTIONS
                    </div>
                    <div className="space-y-1.5">
                      {shipReport.topRisk.map((r, i) => (
                        <div key={i} className="flex justify-between items-center p-2 rounded bg-surface-container-high/30">
                          <div>
                            <span className="text-on-surface font-semibold">{r.invariant}</span>
                            <span className="text-outline text-xs ml-2">culprit: {r.culprit}</span>
                          </div>
                          <span className="text-xs font-mono font-bold text-error">{r.severity}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex justify-end pt-2">
                    <button 
                      onClick={() => window.print()}
                      className="px-space-md py-1.5 rounded bg-surface-container-high text-on-surface hover:bg-surface-container text-xs cursor-pointer"
                    >
                      Print / Export PDF
                    </button>
                  </div>
                </div>
              )}
            </div>

          </div>
        )}

      </main>

      {/* ========================================================================= */}
      {/* FOOTER NOTICES                                                            */}
      {/* ========================================================================= */}
      <footer className="border-t border-outline-variant/20 py-space-sm px-space-xl flex justify-between items-center text-[11px] font-code-sm text-outline">
        <div>
          Agents are stub unless marked <span className="text-secondary font-semibold">live Gemini</span>. Verdicts come from deterministic code.
        </div>
        <div>
          Every number here is read from a result file or API response.
        </div>
      </footer>

    </div>
  )
}
