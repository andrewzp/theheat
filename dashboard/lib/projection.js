export const DASHBOARD_STATE_KEYS = [
  "last_hot10",
  "streaks",
  "errors",
  "daily_tweet_count",
  "run_history",
  "credential_expiry",
]

export function projectStateForDashboard(state = {}) {
  return {
    last_hot10: state.last_hot10 || { date: null, cities: [] },
    streaks: state.streaks || {},
    errors: state.errors || [],
    daily_tweet_count: state.daily_tweet_count || {},
    run_history: state.run_history || [],
    credential_expiry: state.credential_expiry || {},
  }
}
