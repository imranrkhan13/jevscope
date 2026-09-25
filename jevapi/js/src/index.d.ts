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

// ---------- Jev (TypeSafe's decision model) ----------
export type JevProvider = "typesafe" | "venice" | "openrouter";
export const JEV_PROVIDERS: Record<JevProvider, { url: string; model: string }>;
export const NOT_STATED: "not_stated";
export const MAX_OPTIONS: number;
export const MAX_DISCOVERED: number;
export interface JevAnswer { type: "noul" | "choice" | "score"; noul?: number; choice?: string; score?: number; confidence?: number; probabilities?: Record<string, number>; legend?: Record<string, string> }
export interface Normalized { answerType: "noul" | "choice" | "score"; prediction: string; certainty: number; reportedConfidence: number | null; distributionCertainty: number | null; raw: JevAnswer }
export function normalize(answer: JevAnswer): Normalized;
export function correctnessProbability(norm: Normalized): number;
export interface JevField { name: string; label?: string; description?: string; value?: string | number | boolean | null; options?: string[] }
export function discoverFields(text: string, limit?: number): { name: string; label: string; value: string }[];
export function buildQuestions(fields: JevField[]): Record<string, object>;
export function answersToItems(fields: JevField[], answers: Record<string, JevAnswer>): (Item & { label?: string; jev: object | null })[];
export class JevError extends Error { status?: number }
export function askJev(o: { state: unknown; questions: Record<string, object>; key: string; provider?: JevProvider; model?: string; fetchImpl?: typeof fetch; timeoutMs?: number }): Promise<{ answers?: Record<string, JevAnswer>; usage?: object; model?: string }>;
export function checkFields(o: { document: string; fields?: JevField[] | null; key: string; provider?: JevProvider; model?: string; fetchImpl?: typeof fetch; timeoutMs?: number }): Promise<{ items: (Item & { label?: string; jev: object | null })[]; usage: object | null; model: string | null }>;
export interface DiscoveredField { name: string; label: string; value: string | null }
export function isResume(text: string): boolean;
export function resumeFields(text: string, limit?: number): DiscoveredField[];
export function isReceipt(text: string): boolean;
export function receiptFields(text: string, limit?: number): DiscoveredField[];
export const MAX_RECEIPT_FIELDS: number;
export const MAX_RECEIPT_ITEMS: number;
export function isBankStatement(text: string): boolean;
export function statementFields(text: string, limit?: number): DiscoveredField[];
export const MAX_STATEMENT_FIELDS: number;
export const MAX_STATEMENT_TXNS: number;
export function isForm(text: string): boolean;
export function formFields(text: string, limit?: number): DiscoveredField[];
export const MAX_FORM_FIELDS: number;

export type ExtractField = { name: string; label?: string; kind?: "amount" | "date" | "id" | "text" | "any"; maxCandidates?: number };
export function fieldKind(name?: string): "amount" | "date" | "id" | "text" | "any";
export function candidateSpans(document: unknown, field: string | ExtractField): string[];
export function buildExtractQuestions(fields: (string | ExtractField)[], document: unknown): { questions: Record<string, object>; map: { field: ExtractField; candidates: string[] }[] };
export function extractByVerification(o: { document: unknown; fields: (string | ExtractField)[]; key: string; provider?: JevProvider; model?: string; fetchImpl?: typeof fetch; timeoutMs?: number; minConfidence?: number }): Promise<{ items: { field: string; label?: string; value: string | null; confidence: number | null; jev: { type: "extract"; candidates: number; top: string | null; abstained?: boolean } }[]; usage?: object | null; model?: string | null }>;
