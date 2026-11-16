import { describe, expect, it } from 'vitest';
import { QualityGuard } from './quality';

const calm = { stalls: 0, frames: 30, dropped: 0, frozen: false };
const struggling = { stalls: 1, frames: 30, dropped: 0, frozen: false };

describe('QualityGuard', () => {
	it('steps down after a few bad checks in a row, not while a stream starts', () => {
		const guard = new QualityGuard(['main', 'sub', 'low'], 0, 0);
		expect(guard.check(struggling, 2000)).toBe('main'); // starting: stalls are normal
		expect(guard.check(struggling, 8000)).toBe('main');
		expect(guard.check(struggling, 12_000)).toBe('main');
		expect(guard.check(struggling, 14_000)).toBe('main');
		expect(guard.check(struggling, 16_000)).toBe('sub');
		expect(guard.check(calm, 18_000)).toBe('sub');
	});

	it('takes one frozen check for a slow keyframe', () => {
		const guard = new QualityGuard(['main', 'sub'], 0, 0);
		const frozen = { ...calm, frozen: true };
		for (const t of [12_000, 16_000, 20_000])
			expect(guard.check({ ...frozen, frozen: t !== 16_000 }, t)).toBe('main');
	});

	it('counts dropped frames and frozen video as struggling', () => {
		expect(QualityGuard.bad({ ...calm, dropped: 10 })).toBe(true);
		expect(QualityGuard.bad({ ...calm, frozen: true })).toBe(true);
		expect(QualityGuard.bad(calm)).toBe(false);
	});

	it('tries one step up after a calm, and waits longer when that fails', () => {
		const guard = new QualityGuard(['main', 'sub'], 1, 0);
		expect(guard.check(calm, 119_000)).toBe('sub');
		expect(guard.check(calm, 121_000)).toBe('main'); // two calm minutes: try HD
		expect(guard.down(125_000)).toBe('sub'); // it didn't hold
		expect(guard.check(calm, 125_000 + 121_000)).toBe('sub'); // now it waits 4 minutes
		expect(guard.check(calm, 125_000 + 241_000)).toBe('main');
	});

	it('stays at the last step', () => {
		const guard = new QualityGuard(['low'], 0, 0);
		expect(guard.down(1000)).toBe('low');
	});
});
