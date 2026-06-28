import type { ReverseDcfBase, ReverseDcfYear } from "./types";

export type ReverseDcfInputs = {
  n1: number;
  n2: number;
  wacc: number;
  terminalGrowth: number;
  referenceDecay: number;
};

export type ReverseDcfPoint = {
  g1: number;
  g2: number;
  ev: number;
  equityValue: number;
  pvFcff: number;
  terminalValue: number;
  terminalPv: number;
  terminalShareOfMarket: number;
  k: number | null;
};

export type ModelSegmentCagr = {
  g1: number | null;
  g2: number | null;
};

const EPS = 1e-9;

export function clampValue(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function defaultReverseDcfInputs(base: ReverseDcfBase): ReverseDcfInputs {
  const inputs = {
    n1: base.defaults.n1,
    n2: base.defaults.n2,
    wacc: base.defaults.wacc,
    terminalGrowth: base.defaults.terminal_growth,
    referenceDecay: base.defaults.reference_decay,
  };
  const anchoredWacc = solveWaccForModelG1Parity(base, inputs);
  return anchoredWacc == null ? inputs : { ...inputs, wacc: anchoredWacc };
}

function yearAt(base: ReverseDcfBase, index: number): ReverseDcfYear | null {
  if (!base.yearly.length) return null;
  return base.yearly[Math.min(index - 1, base.yearly.length - 1)];
}

function profitAt(baseNopat: number, index: number, n1: number, g1: number, g2: number): number {
  const explicitYears = Math.min(index, n1);
  const midYears = Math.max(0, index - n1);
  return baseNopat * ((1 + g1) ** explicitYears) * ((1 + g2) ** midYears);
}

export function evaluateReverseDcf(
  base: ReverseDcfBase,
  inputs: ReverseDcfInputs,
  g1: number,
  g2: number,
): ReverseDcfPoint | null {
  if (!Number.isFinite(base.base_model.base_nopat)) return null;
  if (!Number.isFinite(g1) || !Number.isFinite(g2) || g1 <= -1 || g2 <= -1) return null;
  if (!Number.isFinite(inputs.wacc) || !Number.isFinite(inputs.terminalGrowth)) return null;
  if (inputs.wacc <= inputs.terminalGrowth + EPS) return null;

  const horizon = Math.max(1, Math.round(inputs.n1) + Math.round(inputs.n2));
  let pvFcff = 0;
  let nopat = base.base_model.base_nopat;

  for (let index = 1; index <= horizon; index += 1) {
    const year = yearAt(base, index);
    if (!year) return null;
    nopat = profitAt(base.base_model.base_nopat, index, inputs.n1, g1, g2);
    const fcffToNopat = Number.isFinite(year.fcff_to_nopat) ? year.fcff_to_nopat : year.fcff / year.nopat;
    if (!Number.isFinite(fcffToNopat)) return null;
    const fcff = nopat * fcffToNopat;
    pvFcff += fcff / ((1 + inputs.wacc) ** index);
  }

  const terminalYear = yearAt(base, horizon);
  if (!terminalYear) return null;
  const terminalFcffToNopat = Number.isFinite(terminalYear.terminal_fcff_to_nopat)
    ? terminalYear.terminal_fcff_to_nopat
    : 1 + (terminalYear.da / terminalYear.nopat) * (1 - base.defaults.terminal_capex_da_ratio);
  if (!Number.isFinite(terminalFcffToNopat)) return null;
  const terminalFcff = nopat * terminalFcffToNopat;
  const terminalValue = terminalFcff * (1 + inputs.terminalGrowth) / (inputs.wacc - inputs.terminalGrowth);
  const terminalPv = terminalValue / ((1 + inputs.wacc) ** horizon);
  const ev = pvFcff + terminalPv;
  const equityValue = ev - base.market.net_debt;
  return {
    g1,
    g2,
    ev,
    equityValue,
    pvFcff,
    terminalValue,
    terminalPv,
    terminalShareOfMarket: base.market.market_cap > EPS ? terminalPv / base.market.market_cap : 0,
    k: Math.abs(g1) > EPS ? g2 / g1 : null,
  };
}

function solveG2(
  base: ReverseDcfBase,
  inputs: ReverseDcfInputs,
  g1: number,
  targetEquityValue: number,
  low: number,
  high: number,
): ReverseDcfPoint | null {
  const gap = (g2: number): number | null => {
    const point = evaluateReverseDcf(base, inputs, g1, g2);
    return point ? point.equityValue - targetEquityValue : null;
  };

  let lo = low;
  let hi = high;
  let fLo = gap(lo);
  let fHi = gap(hi);
  if (fLo == null || fHi == null) return null;
  if (Math.abs(fLo) < EPS) return evaluateReverseDcf(base, inputs, g1, lo);
  if (Math.abs(fHi) < EPS) return evaluateReverseDcf(base, inputs, g1, hi);
  if (Math.sign(fLo) === Math.sign(fHi)) return null;

  for (let i = 0; i < 70; i += 1) {
    const mid = (lo + hi) / 2;
    const fMid = gap(mid);
    if (fMid == null) return null;
    if (Math.abs(fMid) < 1e-6) return evaluateReverseDcf(base, inputs, g1, mid);
    if (Math.sign(fMid) === Math.sign(fLo)) {
      lo = mid;
      fLo = fMid;
    } else {
      hi = mid;
      fHi = fMid;
    }
  }
  return evaluateReverseDcf(base, inputs, g1, (lo + hi) / 2);
}

export function generateIsoCurve(
  base: ReverseDcfBase,
  inputs: ReverseDcfInputs,
  options: { samples?: number; visibleDomain?: [number, number]; solveDomain?: [number, number] } = {},
): ReverseDcfPoint[] {
  if (inputs.wacc <= inputs.terminalGrowth + EPS) return [];
  const samples = options.samples ?? 181;
  const visibleDomain = options.visibleDomain ?? base.bounds.growth;
  const solveDomain = options.solveDomain ?? [-0.5, 0.8];
  const points: ReverseDcfPoint[] = [];
  for (let i = 0; i < samples; i += 1) {
    const g1 = visibleDomain[0] + ((visibleDomain[1] - visibleDomain[0]) * i) / Math.max(1, samples - 1);
    const point = solveG2(base, inputs, g1, base.market.market_cap, solveDomain[0], solveDomain[1]);
    if (point && point.g2 >= visibleDomain[0] - EPS && point.g2 <= visibleDomain[1] + EPS) {
      points.push(point);
    }
  }
  return points;
}

export function nearestCurvePoint(curve: ReverseDcfPoint[], g1: number, g2: number): ReverseDcfPoint | null {
  let best: ReverseDcfPoint | null = null;
  let bestScore = Infinity;
  for (const point of curve) {
    const score = ((point.g1 - g1) ** 2) + ((point.g2 - g2) ** 2);
    if (score < bestScore) {
      best = point;
      bestScore = score;
    }
  }
  return best;
}

export function referenceIntersection(
  base: ReverseDcfBase,
  inputs: ReverseDcfInputs,
  curve: ReverseDcfPoint[],
): ReverseDcfPoint | null {
  if (!curve.length) return null;
  const residual = (point: ReverseDcfPoint) => point.g2 - inputs.referenceDecay * point.g1;
  for (let i = 1; i < curve.length; i += 1) {
    const prev = curve[i - 1];
    const next = curve[i];
    const rPrev = residual(prev);
    const rNext = residual(next);
    if (Math.abs(rPrev) < EPS) return prev;
    if (Math.sign(rPrev) !== Math.sign(rNext)) {
      const t = Math.abs(rPrev) / (Math.abs(rPrev) + Math.abs(rNext));
      const g1 = prev.g1 + (next.g1 - prev.g1) * t;
      const g2 = prev.g2 + (next.g2 - prev.g2) * t;
      return evaluateReverseDcf(base, inputs, g1, g2) ?? nearestCurvePoint(curve, g1, g2);
    }
  }
  return curve.reduce((best, point) => (Math.abs(residual(point)) < Math.abs(residual(best)) ? point : best), curve[0]);
}

export function referencePointForTargetG2(
  base: ReverseDcfBase,
  inputs: ReverseDcfInputs,
  targetG2: number | null | undefined,
  options: { samples?: number; solveDomain?: [number, number] } = {},
): ReverseDcfPoint | null {
  if (typeof targetG2 !== "number" || !Number.isFinite(targetG2)) return null;
  if (targetG2 <= -1) return null;
  if (inputs.wacc <= inputs.terminalGrowth + EPS) return null;

  const solveDomain = options.solveDomain ?? base.bounds.growth;
  if (targetG2 < solveDomain[0] - EPS || targetG2 > solveDomain[1] + EPS) return null;

  const gap = (g1: number): number | null => {
    const point = evaluateReverseDcf(base, inputs, g1, targetG2);
    return point ? point.equityValue - base.market.market_cap : null;
  };

  const solveBracket = (low: number, high: number): ReverseDcfPoint | null => {
    let lo = low;
    let hi = high;
    let fLo = gap(lo);
    let fHi = gap(hi);
    if (fLo == null || fHi == null) return null;
    if (Math.abs(fLo) < EPS) return evaluateReverseDcf(base, inputs, lo, targetG2);
    if (Math.abs(fHi) < EPS) return evaluateReverseDcf(base, inputs, hi, targetG2);
    if (Math.sign(fLo) === Math.sign(fHi)) return null;

    for (let i = 0; i < 70; i += 1) {
      const mid = (lo + hi) / 2;
      const fMid = gap(mid);
      if (fMid == null) return null;
      if (Math.abs(fMid) < 1e-6) return evaluateReverseDcf(base, inputs, mid, targetG2);
      if (Math.sign(fMid) === Math.sign(fLo)) {
        lo = mid;
        fLo = fMid;
      } else {
        hi = mid;
        fHi = fMid;
      }
    }
    return evaluateReverseDcf(base, inputs, (lo + hi) / 2, targetG2);
  };

  const samples = options.samples ?? 181;
  let prevG1 = solveDomain[0];
  let prevGap = gap(prevG1);
  if (prevGap != null && Math.abs(prevGap) < EPS) {
    return evaluateReverseDcf(base, inputs, prevG1, targetG2);
  }

  for (let i = 1; i < samples; i += 1) {
    const g1 = solveDomain[0] + ((solveDomain[1] - solveDomain[0]) * i) / Math.max(1, samples - 1);
    const currentGap = gap(g1);
    if (currentGap == null) continue;
    if (Math.abs(currentGap) < EPS) return evaluateReverseDcf(base, inputs, g1, targetG2);
    if (prevGap != null && Math.sign(prevGap) !== Math.sign(currentGap)) {
      return solveBracket(prevG1, g1);
    }
    prevG1 = g1;
    prevGap = currentGap;
  }

  return null;
}

export function solveWaccForModelG1Parity(
  base: ReverseDcfBase,
  inputs: ReverseDcfInputs,
  options: { tolerance?: number } = {},
): number | null {
  const modelCagr = modelSegmentCagr(base, inputs.n1, inputs.n2);
  const g1 = modelCagr.g1;
  const g2 = modelCagr.g2;
  if (g1 == null || g2 == null) return null;
  if (!Number.isFinite(g1) || !Number.isFinite(g2)) return null;
  if (g1 <= -1 || g2 <= -1) return null;

  const low = Math.max(base.bounds.wacc[0], inputs.terminalGrowth + 0.001);
  const high = base.bounds.wacc[1];
  if (!Number.isFinite(low) || !Number.isFinite(high) || low >= high) return null;

  const gap = (wacc: number): number | null => {
    const point = evaluateReverseDcf(base, { ...inputs, wacc }, g1, g2);
    return point ? point.equityValue - base.market.market_cap : null;
  };

  let lo = low;
  let hi = high;
  let fLo = gap(lo);
  let fHi = gap(hi);
  const tolerance = options.tolerance ?? 1e-6;
  if (fLo == null || fHi == null) return null;
  if (Math.abs(fLo) < tolerance) return lo;
  if (Math.abs(fHi) < tolerance) return hi;
  if (Math.sign(fLo) === Math.sign(fHi)) return null;

  for (let i = 0; i < 70; i += 1) {
    const mid = (lo + hi) / 2;
    const fMid = gap(mid);
    if (fMid == null) return null;
    if (Math.abs(fMid) < tolerance) return mid;
    if (Math.sign(fMid) === Math.sign(fLo)) {
      lo = mid;
      fLo = fMid;
    } else {
      hi = mid;
      fHi = fMid;
    }
  }
  return (lo + hi) / 2;
}

function compoundCagr(rates: number[], start: number, length: number): number | null {
  if (length <= 0 || start >= rates.length) return null;
  const slice = rates.slice(start, start + length);
  if (slice.length < length || slice.some((rate) => !Number.isFinite(rate) || rate <= -1)) return null;
  const product = slice.reduce((acc, rate) => acc * (1 + rate), 1);
  return (product ** (1 / length)) - 1;
}

export function modelSegmentCagr(base: ReverseDcfBase, n1: number, n2: number): ModelSegmentCagr {
  const rates = Array.isArray(base.base_model.current_model_profit_yoy)
    ? base.base_model.current_model_profit_yoy
    : [];
  return {
    g1: compoundCagr(rates, 0, n1),
    g2: compoundCagr(rates, n1, n2),
  };
}

export function pointInDomain(point: { g1: number; g2: number } | null, domain: [number, number]): boolean {
  if (!point) return false;
  return point.g1 >= domain[0] && point.g1 <= domain[1] && point.g2 >= domain[0] && point.g2 <= domain[1];
}
