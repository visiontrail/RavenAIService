/**
 * Numeric knobs of the model-routing policy, in Admin form order.
 *
 * `min`/`max` mirror `model_settings_service._ROUTER_BOUNDS` so the number
 * inputs give immediate feedback. They are **not** the validation: the browser
 * happily submits an out-of-range number, and the rules that actually matter
 * are cross-field (trip ≤ window, deadline ≥ slow) and can only be judged
 * against the merged post-save state. The backend rejects with a 400 whose
 * detail is surfaced verbatim.
 *
 * Extracted from the view so both the bounds mirror and the i18n keys can be
 * tested — a typo in a `t()` key inside a template literal renders as the raw
 * key string and no catalog-parity check would notice.
 */
export type RouterKnobKey =
  | 'model_router_first_token_deadline_ms'
  | 'model_router_slow_ttft_ms'
  | 'model_router_window_size'
  | 'model_router_trip_threshold'
  | 'model_router_min_samples'
  | 'model_router_hard_failure_trip'
  | 'model_router_cooldown_seconds'
  | 'model_router_sample_ttl_seconds'

export interface RouterKnob {
  key: RouterKnobKey
  /** i18n key under `admin.modelSettings`. */
  label: string
  hint: string
  min: number
  max: number
}

export const ROUTER_KNOBS: RouterKnob[] = [
  {
    key: 'model_router_first_token_deadline_ms',
    label: 'routerDeadlineLabel',
    hint: 'routerDeadlineHint',
    min: 0,
    max: 600000,
  },
  {
    key: 'model_router_slow_ttft_ms',
    label: 'routerSlowLabel',
    hint: 'routerSlowHint',
    min: 1000,
    max: 600000,
  },
  {
    key: 'model_router_window_size',
    label: 'routerWindowLabel',
    hint: 'routerWindowHint',
    min: 1,
    max: 100,
  },
  {
    key: 'model_router_trip_threshold',
    label: 'routerTripLabel',
    hint: 'routerTripHint',
    min: 1,
    max: 100,
  },
  {
    key: 'model_router_min_samples',
    label: 'routerMinSamplesLabel',
    hint: 'routerMinSamplesHint',
    min: 1,
    max: 100,
  },
  {
    key: 'model_router_hard_failure_trip',
    label: 'routerHardFailLabel',
    hint: 'routerHardFailHint',
    min: 1,
    max: 100,
  },
  {
    key: 'model_router_cooldown_seconds',
    label: 'routerCooldownLabel',
    hint: 'routerCooldownHint',
    min: 10,
    max: 86400,
  },
  {
    key: 'model_router_sample_ttl_seconds',
    label: 'routerSampleTtlLabel',
    hint: 'routerSampleTtlHint',
    min: 60,
    max: 86400,
  },
]
