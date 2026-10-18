"use client"

import React from "react"

const h = React.createElement
const FAMILY = {
  mixed: "Mixed products; retain each product's provenance",
  forecast_model: "Model or forecast product",
  station_points: "Dated station or point product",
  satellite_analysis: "Satellite or gridded analysis",
  official_warning: "Issued warning or advisory",
  official_report: "Official report or event product",
  derived_index: "Derived series or index",
  discovery: "Discovery evidence; qualification still required",
}

export function SourceContractDetails({ contract }) {
  const internal = contract?.kind === "internal"
  if (!contract?.registered) return h("details", { className: "source-contract" },
    h("summary", null, internal ? "About this workflow entry" : "Scope not registered"),
    h("p", null, internal
      ? "This is workflow telemetry, not an independent weather source."
      : "A saved label does not establish geography, time basis or claim permissions. Its source contract is unknown."))
  const items = [
    ["Where it looks", contract.scope],
    ["What it uses", FAMILY[contract.data_family] || "Unqualified product type"],
    ["Provenance", contract.provenance],
    ["When the collector checks", contract.collection_rule],
    ["Time basis", contract.time_rule],
    ["Story limits", contract.claim_limit],
  ]
  return h("details", { className: "source-contract" },
    h("summary", null, "Scope and limits"),
    h("dl", null, ...items.map(([label, value]) => h("div", { key: label },
      h("dt", null, label), h("dd", null, value || "Unknown")))),
    h("p", null, contract.claim_policy),
    h("p", { className: "source-contract-unknown" },
      "Not verified by this inventory: access, provider quotas, reuse rights, story qualification or complete event coverage. Collection rules do not promise when the provider updates."))
}
