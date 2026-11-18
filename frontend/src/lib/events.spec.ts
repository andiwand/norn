import { describe, expect, it } from 'vitest';
import type { Recording } from './api';
import { groupEvents, heatMap, videoLength } from './events';

function clip(camera: string, start: string, seconds = 50, trigger = 'person', pinned = false) {
	const day = start.slice(0, 10);
	const name = `${start.slice(11, 19).replaceAll(':', '-')}_${trigger}.mp4`;
	return {
		id: `${camera}/${day}/${name}`,
		camera,
		day,
		name,
		kind: 'video',
		start: new Date(start).toISOString(),
		trigger,
		size: 1,
		duration: seconds,
		thumbnail: true,
		expires: null,
		pinned,
		meta: {}
	} satisfies Recording;
}

describe('groupEvents', () => {
	it('merges a burst of one camera into one event', () => {
		const events = groupEvents([
			clip('cam', '2026-11-18T05:00:00'),
			clip('cam', '2026-11-18T05:03:00'), // 2 min 10 s after the first ended
			clip('cam', '2026-11-18T05:07:00', 30, 'motion', true)
		]);
		expect(events).toHaveLength(1);
		const [e] = events;
		expect(e.clips.map((c) => c.start)).toEqual(
			['05:00', '05:03', '05:07'].map((t) => new Date(`2026-11-18T${t}:00`).toISOString())
		);
		expect(e.triggers).toEqual([
			['person', 2],
			['motion', 1]
		]);
		expect(e.seconds).toBe(130);
		expect(e.pinned).toBe(1);
		expect(e.end - e.start).toBe(7.5 * 60_000);
	});

	it('splits on a long gap, by camera and at midnight; newest first', () => {
		const events = groupEvents([
			clip('a', '2026-11-18T05:00:00'),
			clip('b', '2026-11-18T05:01:00'),
			clip('a', '2026-11-18T05:30:00'), // 29 min later: a new event
			clip('a', '2026-11-17T23:58:00'),
			clip('a', '2026-11-18T00:00:30') // close, but the next day
		]);
		expect(events.map((e) => [e.camera, e.clips.length, e.day])).toEqual([
			['a', 1, '2026-11-18'],
			['b', 1, '2026-11-18'],
			['a', 1, '2026-11-18'],
			['a', 1, '2026-11-18'],
			['a', 1, '2026-11-17']
		]);
		expect(groupEvents([])).toEqual([]);
	});
});

describe('heatMap', () => {
	it('counts clips per camera and hour up to now', () => {
		const now = new Date('2026-11-18T20:40:00').getTime();
		const map = heatMap(
			[
				clip('a', '2026-11-18T20:05:00'),
				clip('a', '2026-11-18T20:35:00'),
				clip('b', '2026-11-17T21:10:00'), // the oldest hour shown
				clip('b', '2026-11-17T20:59:00'), // before it
				clip('x', '2026-11-18T20:10:00') // not a camera shown
			],
			['a', 'b'],
			now
		);
		expect(map.starts).toHaveLength(24);
		expect(map.starts[23]).toBe(new Date('2026-11-18T20:00:00').getTime());
		expect(map.rows[0].counts[23]).toBe(2);
		expect(map.rows[1].counts[0]).toBe(1);
		expect(map.rows[1].counts.reduce((a, b) => a + b)).toBe(1);
		expect(map.max).toBe(2);
	});

	it('over days, takes squares of a few hours that start on the clock', () => {
		const now = new Date('2026-11-18T20:40:00').getTime();
		const week = heatMap([clip('a', '2026-11-12T00:30:00')], ['a'], now, 7);
		expect(week.starts).toHaveLength(28);
		expect(week.starts[27]).toBe(new Date('2026-11-18T18:00:00').getTime());
		expect(week.starts[0]).toBe(new Date('2026-11-12T00:00:00').getTime());
		expect(week.rows[0].counts[0]).toBe(1);
		const three = heatMap([], ['a'], now, 3);
		expect(three.starts).toHaveLength(24);
		expect(three.starts[23]).toBe(new Date('2026-11-18T18:00:00').getTime());
		// Every square starts on the clock, whatever the zone and its summer time.
		const march = heatMap([], ['a'], new Date('2026-03-31T10:00:00').getTime(), 7);
		expect(march.starts.every((t) => new Date(t).getHours() % 6 === 0)).toBe(true);
	});
});

describe('videoLength', () => {
	it('says how long in words', () => {
		expect(videoLength(50)).toBe('50 s');
		expect(videoLength(26 * 60 + 10)).toBe('26 min');
		expect(videoLength(125 * 60)).toBe('2 h 5 min');
		expect(videoLength(120 * 60)).toBe('2 h');
	});
});
