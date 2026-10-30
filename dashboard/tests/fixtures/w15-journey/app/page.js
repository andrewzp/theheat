"use client"
import { useEffect, useState } from "react"
import PostFeedback from "../../../../app/components/PostFeedback.js"
import PostOutcomeHistory from "../../../../app/components/PostOutcomeHistory.js"
import CoverageEvidence from "../../../../app/components/CoverageEvidence.js"
import { ProductHealthPanel } from "../../../../app/components/ProductHealthPanel.js"
export default function Journey() {
  const [dashboard, setDashboard] = useState(null), [outcomes, setOutcomes] = useState(null), [error, setError] = useState("")
  async function refresh() {
    const [d, o] = await Promise.all([fetch("/api/dashboard", { cache: "no-store" }), fetch("/api/fixture-outcomes", { cache: "no-store" })])
    if (!d.ok || !o.ok) throw new Error("Invented fixture refresh failed")
    setDashboard(await d.json()); setOutcomes(await o.json())
  }
  useEffect(() => { refresh().catch(e => setError(e.message)) }, [])
  return <main className="container">
    <h1>Invented W15 feedback, outcome and coverage journey</h1>
    <p>Actual feedback and dashboard handlers over invented in-memory Gists. No publication, source or platform request.</p>
    {error && <p role="alert">{error}</p>}
    <button type="button" className="btn" onClick={() => refresh().catch(e => setError(e.message))}>Refresh outcome views</button>
    <PostFeedback />
    {dashboard && <ProductHealthPanel health={dashboard.productHealth} config={dashboard.config} deployment={dashboard.deployment} />}
    {outcomes && <section aria-label="Outcome view with supplied feedback and corrections" className="card full">
      <h2>Outcome view with supplied feedback and corrections (fixture join)</h2>
      <PostOutcomeHistory outcomes={outcomes} />
    </section>}
    <CoverageEvidence readOnly />
  </main>
}
