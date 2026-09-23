export const PROFILE_VERSION: 1;

export interface Example { field?: string | null; confidence: number; correct: boolean }
export interface Item { field?: string | null; value: unknown; confidence: number | null | undefined }

export interface Options {
  /** Cost of one wrong auto-fill, in units of one human check. Default 20. */
  costError?: number;
  /** Cost of one human check. Default 1. */
  costReview?: number;
  /** Share of human checks that catch the error. Default 1. */
  reviewAccuracy?: number;
  /** Never auto-fill when the chance of being wrong is above this (0-1). */
  maxRisk?: number | null;
  /** Examples a field needs before it gets its own calibration. Default 30. */
  minExamples?: number;
  /** Decide on the lower confidence bound instead of the point estimate. Default true. */
  conservative?: boolean;
  /** z for the one-sided Wilson lower bound. Default 1.2816 (90%). */
  z?: number;
  /** Extra per-field check; returning false sends the field to review. Not saved in profiles. */
  validate?: (value: unknown) => boolean;
}

export interface CalibrateOptions extends Options { fields?: Record<string, Options> }

export interface Block { lo: number; hi: number; k: number; n: number; p: number; lower: number }
export interface FieldProfile { n: number; accuracy: number | null; own: boolean; blocks: Block[]; options: Options }
export interface Profile { version: 1; n: number; defaults: Options; pooled: Block[]; fields: Record<string, FieldProfile> }

export interface Decision {
  field: string;
  action: "fill" | "review";
  confidence: number | null;
  lower: number | null;
  threshold: number;
  calibrated: boolean;
  source?: "field" | "pooled" | "raw";
  reason: string;
}

export interface Summary {
  n: number; accuracy: number; coverage: number; autoErrorRate: number; autoErrors: number;
  eceRaw: number; eceCalibrated: number; savingsVsManual: number;
}

export function calibrate(examples: Example[], options?: CalibrateOptions): Profile;
export function validateProfile(profile: Profile): Profile;
export function decide(profile: Profile | null, item: Item, overrides?: Options): Decision;
export function decideAll(profile: Profile | null, items: Item[], overrides?: Options): { decisions: Decision[]; fill: number; review: number };
export function evaluate(examples: Example[], options?: CalibrateOptions, k?: number): { k: number; overall: Summary; fields: Record<string, Summary> };
export function fitIsotonic(examples: Example[], z?: number): Block[];
export function applyIsotonic(blocks: Block[], x: number, key?: "p" | "lower"): number | null;
export function ece(confidences: number[], correct: boolean[], nBins?: number): number;
export function costThreshold(o: { costError: number; costReview: number; reviewAccuracy: number }): number;
export function wilsonLower(k: number, n: number, z?: number): number;
