// Mirror of src/two_bot/cost_inputs.register(); parity-tested by
// tests/final_closure/test_cost_inputs.py. States inputs only: no price, no total.
export const COST_INPUTS = {
  "actual_charge_known": false,
  "billing_export_input": {
    "command": "scripts/reconcile_request_archive.py import-export",
    "files": [
      "provider billing export CSV for one period",
      "theheat.billing-export-profile/v1 JSON profile"
    ],
    "kind": "billing_export_import",
    "profile_columns": {
      "optional": [
        "item_id",
        "currency",
        "kind",
        "quantity",
        "quantity_unit",
        "model",
        "provider_request_id",
        "provider_response_id",
        "occurred_at"
      ],
      "required": [
        "amount"
      ]
    },
    "profile_required_fields": [
      "schema",
      "provider",
      "scope",
      "currency",
      "period",
      "coverage",
      "columns"
    ]
  },
  "ceilings": {
    "candidate_attempts": {
      "enforced": true,
      "financial_cap": false
    },
    "daily_publication_cap": {
      "enforced": true,
      "financial_cap": false
    },
    "estimated_token_cap": {
      "enforced": true,
      "financial_cap": false
    },
    "invoice_ceiling": {
      "enforced": false,
      "financial_cap": true
    },
    "local_spend_allowance": {
      "enforced": true,
      "financial_cap": false
    },
    "monthly_budget_watch": {
      "enforced": false,
      "financial_cap": false
    },
    "provider_call_cap": {
      "enforced": true,
      "financial_cap": false
    }
  },
  "evidence_added_together": false,
  "evidence_kinds": [
    "estimate",
    "observation",
    "invoice"
  ],
  "monthly_provider_ceiling_enforced": false,
  "rows": [
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "anthropic_price_table",
        "models": [
          "claude-haiku-4-5",
          "claude-sonnet-4-6"
        ],
        "unpriced": [
          "actual_charge",
          "other_models"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "estimate_partial",
      "provider": "anthropic",
      "spend_class": "selection",
      "stage": "writer"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "gemini_token_scenario",
        "models": [
          "gemini-2.5-flash",
          "gemini-2.5-pro",
          "gemini-3.8-flash"
        ],
        "unpriced": [
          "actual_charge",
          "other_models",
          "tool_and_grounding_charges"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "estimate_partial",
      "provider": "google",
      "spend_class": "selection",
      "stage": "writer"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "gemini_token_scenario",
        "models": [
          "gemini-2.5-flash",
          "gemini-2.5-pro",
          "gemini-3.8-flash"
        ],
        "unpriced": [
          "actual_charge",
          "other_models",
          "tool_and_grounding_charges"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "estimate_partial",
      "provider": "google",
      "spend_class": "selection",
      "stage": "safety"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "gemini_token_scenario",
        "models": [
          "gemini-2.5-flash",
          "gemini-2.5-pro",
          "gemini-3.8-flash"
        ],
        "unpriced": [
          "actual_charge",
          "other_models",
          "tool_and_grounding_charges"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "estimate_partial",
      "provider": "google",
      "spend_class": "selection",
      "stage": "fact_check"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "gemini_token_scenario",
        "models": [
          "gemini-2.5-flash",
          "gemini-2.5-pro",
          "gemini-3.8-flash"
        ],
        "unpriced": [
          "actual_charge",
          "other_models",
          "tool_and_grounding_charges"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "estimate_partial",
      "provider": "google",
      "spend_class": "selection",
      "stage": "critic"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "gemini_token_scenario",
        "models": [
          "gemini-2.5-flash",
          "gemini-2.5-pro",
          "gemini-3.8-flash"
        ],
        "unpriced": [
          "actual_charge",
          "other_models",
          "search_grounding_tool",
          "tool_and_grounding_charges"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "estimate_partial",
      "provider": "google",
      "spend_class": "discovery",
      "stage": "newsworthiness_search"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "gemini_token_scenario",
        "models": [
          "gemini-2.5-flash",
          "gemini-2.5-pro",
          "gemini-3.8-flash"
        ],
        "unpriced": [
          "actual_charge",
          "other_models",
          "tool_and_grounding_charges"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "estimate_partial",
      "provider": "google",
      "spend_class": "discovery",
      "stage": "newsworthiness_verify"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "missing_price",
        "models": [],
        "unpriced": [
          "all_charges",
          "egress"
        ]
      },
      "invoice": {
        "path": "supplied_statement_required",
        "required_input": "No provider bill is expected for public page reads; owner confirmation for the period that no paid access, proxy or egress plan is used"
      },
      "observation": "counted_physical_request",
      "pricing": "unknown",
      "provider": "publisher",
      "spend_class": "discovery",
      "stage": "news_verification_page"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "missing_price",
        "models": [],
        "unpriced": [
          "all_charges",
          "egress",
          "source_plan"
        ]
      },
      "invoice": {
        "path": "supplied_statement_required",
        "required_input": "Per-source data plan or terms statement for the period (public feeds: owner confirmation that no paid plan is used; paid feeds: the plan invoice)"
      },
      "observation": "counted_physical_request",
      "pricing": "unknown",
      "provider": "source",
      "spend_class": "acquisition",
      "stage": "source_http_get"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "missing_price",
        "models": [],
        "unpriced": [
          "all_charges",
          "hosting_plan"
        ]
      },
      "invoice": {
        "path": "supplied_statement_required",
        "required_input": "GitHub billing usage report for the account and period (Actions minutes, storage, API), with amount and currency, or the plan statement showing the included allowance"
      },
      "observation": "counted_physical_request",
      "pricing": "unknown",
      "provider": "github",
      "spend_class": "hosting",
      "stage": "gist_state"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "missing_price",
        "models": [],
        "unpriced": [
          "all_charges",
          "platform_plan"
        ]
      },
      "invoice": {
        "path": "supplied_statement_required",
        "required_input": "X developer account plan statement for the period: plan name, period start/end, amount and currency (or the provider's written no-charge tier for that account and period)"
      },
      "observation": "counted_physical_request",
      "pricing": "unknown",
      "provider": "x",
      "spend_class": "platform",
      "stage": "x_publish"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "missing_price",
        "models": [],
        "unpriced": [
          "all_charges",
          "platform_plan"
        ]
      },
      "invoice": {
        "path": "supplied_statement_required",
        "required_input": "Owner statement that the account incurs no API charge for the period, or the charge document"
      },
      "observation": "counted_physical_request",
      "pricing": "unknown",
      "provider": "bluesky",
      "spend_class": "platform",
      "stage": "bluesky_publish"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "missing_price",
        "models": [],
        "unpriced": [
          "all_charges",
          "platform_plan"
        ]
      },
      "invoice": {
        "path": "supplied_statement_required",
        "required_input": "X developer account plan statement for the period: plan name, period start/end, amount and currency (or the provider's written no-charge tier for that account and period)"
      },
      "observation": "counted_physical_request",
      "pricing": "unknown",
      "provider": "x",
      "spend_class": "maintenance",
      "stage": "x_metrics_read"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "missing_price",
        "models": [],
        "unpriced": [
          "actual_charge",
          "all_charges",
          "batch_discount"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "estimate_partial",
      "provider": "anthropic",
      "spend_class": "selection",
      "stage": "batch_writer"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "anthropic_price_table",
        "models": [
          "claude-haiku-4-5",
          "claude-sonnet-4-6"
        ],
        "unpriced": [
          "actual_charge",
          "other_models"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "estimate_partial",
      "provider": "anthropic",
      "spend_class": "selection",
      "stage": "synchronous_writer"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "gemini_token_scenario",
        "models": [
          "gemini-2.5-flash",
          "gemini-2.5-pro",
          "gemini-3.8-flash"
        ],
        "unpriced": [
          "actual_charge",
          "other_models",
          "tool_and_grounding_charges"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "estimate_partial",
      "provider": "google",
      "spend_class": "selection",
      "stage": "local_required_check"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "anthropic_price_table",
        "models": [
          "claude-haiku-4-5",
          "claude-sonnet-4-6"
        ],
        "unpriced": [
          "actual_charge",
          "other_models"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "unknown",
      "provider": "anthropic",
      "spend_class": "evaluation",
      "stage": "paid_evaluation"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "gemini_token_scenario",
        "models": [
          "gemini-2.5-flash",
          "gemini-2.5-pro",
          "gemini-3.8-flash"
        ],
        "unpriced": [
          "actual_charge",
          "other_models",
          "tool_and_grounding_charges"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "unknown",
      "provider": "google",
      "spend_class": "evaluation",
      "stage": "paid_evaluation"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "anthropic_price_table",
        "models": [
          "claude-haiku-4-5",
          "claude-sonnet-4-6"
        ],
        "unpriced": [
          "actual_charge",
          "other_models"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "unknown",
      "provider": "anthropic",
      "spend_class": "evaluation",
      "stage": "paid_pr_replay"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "gemini_token_scenario",
        "models": [
          "gemini-2.5-flash",
          "gemini-2.5-pro",
          "gemini-3.8-flash"
        ],
        "unpriced": [
          "actual_charge",
          "other_models",
          "tool_and_grounding_charges"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "unknown",
      "provider": "google",
      "spend_class": "evaluation",
      "stage": "paid_pr_replay"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "missing_price",
        "models": [],
        "unpriced": [
          "actual_charge",
          "all_charges"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "counted_physical_request",
      "pricing": "unknown",
      "provider": "anthropic",
      "spend_class": "maintenance",
      "stage": "selfheal_repair"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "missing_price",
        "models": [],
        "unpriced": [
          "actual_charge",
          "all_charges"
        ]
      },
      "invoice": {
        "path": "supplied_statement_required",
        "required_input": "GitHub billing usage report for the account and period (Actions minutes, storage, API), with amount and currency, or the plan statement showing the included allowance"
      },
      "observation": "counted_physical_request",
      "pricing": "unknown",
      "provider": "github",
      "spend_class": "maintenance",
      "stage": "selfheal_repair"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "anthropic_price_table",
        "models": [
          "claude-haiku-4-5",
          "claude-sonnet-4-6"
        ],
        "unpriced": [
          "actual_charge",
          "other_models",
          "undeclared_route"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "unknown",
      "provider": "anthropic",
      "spend_class": "selection",
      "stage": "undeclared_provider_call"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "gemini_token_scenario",
        "models": [
          "gemini-2.5-flash",
          "gemini-2.5-pro",
          "gemini-3.8-flash"
        ],
        "unpriced": [
          "actual_charge",
          "other_models",
          "tool_and_grounding_charges",
          "undeclared_route"
        ]
      },
      "invoice": {
        "path": "billing_export_import",
        "required_input": "billing_export_import"
      },
      "observation": "provider_reported_usage",
      "pricing": "unknown",
      "provider": "google",
      "spend_class": "selection",
      "stage": "undeclared_provider_call"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "missing_price",
        "models": [],
        "unpriced": [
          "all_charges",
          "egress",
          "runner_minutes"
        ]
      },
      "invoice": {
        "path": "supplied_statement_required",
        "required_input": "Owner confirmation that NOAA bulk downloads use public no-charge access for the period, plus the runner-minutes statement (github) for the job"
      },
      "observation": "counted_physical_request",
      "pricing": "unknown",
      "provider": "noaa",
      "spend_class": "acquisition",
      "stage": "threshold_acquisition"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "missing_price",
        "models": [],
        "unpriced": [
          "all_charges"
        ]
      },
      "invoice": {
        "path": "supplied_statement_required",
        "required_input": "GitHub billing usage report for the account and period (Actions minutes, storage, API), with amount and currency, or the plan statement showing the included allowance"
      },
      "observation": "workflow run history (not retained in state)",
      "pricing": "unknown",
      "provider": "github",
      "spend_class": "hosting",
      "stage": "github_actions_runner_minutes"
    },
    {
      "actual_charge_known": false,
      "estimate": {
        "basis": "missing_price",
        "models": [],
        "unpriced": [
          "all_charges"
        ]
      },
      "invoice": {
        "path": "supplied_statement_required",
        "required_input": "Vercel usage/invoice for the dashboard project and period, with amount and currency"
      },
      "observation": "not observed by the bot",
      "pricing": "unknown",
      "provider": "vercel",
      "spend_class": "hosting",
      "stage": "vercel_dashboard_hosting"
    }
  ],
  "schema_version": 1,
  "statement_required_providers": [
    "bluesky",
    "github",
    "noaa",
    "publisher",
    "source",
    "vercel",
    "x"
  ]
}
