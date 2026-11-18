// Clips grouped into events: what happened, rather than file after file. Clips of one camera
// close together (a burst at night) are one event; the heat map counts clips per camera and hour.
import type { Recording } from './api';
import { localDay } from './format';

/** Clips of one camera this close together (end to start) belong to one event: a camera that
 * keeps triggering every few minutes at night is one burst, not dozens of events. */
export const EVENT_GAP = 15 * 60_000;

export interface ClipEvent {
	/** The id of its first clip: stable while clips are added at the end. */
	id: string;
	camera: string;
	/** The browser's day (YYYY-MM-DD) it starts on; an event never spans midnight. */
	day: string;
	/** Oldest first: the order to play them in. */
	clips: Recording[];
	start: number;
	end: number;
	/** What started its clips, the most frequent first. */
	triggers: [string, number][];
	/** Seconds of video in all. */
	seconds: number;
	pinned: number;
}

const startOf = (r: Recording) => new Date(r.start).getTime();
const endOf = (r: Recording) => startOf(r) + (r.duration ?? 0) * 1000;

/** Group clips into events, newest event first. */
export function groupEvents(clips: Recording[], gap = EVENT_GAP): ClipEvent[] {
	const sorted = [...clips].sort((a, b) => startOf(a) - startOf(b));
	const open = new Map<string, Recording[]>(); // the event being built, per camera
	const groups: Recording[][] = [];
	for (const clip of sorted) {
		const current = open.get(clip.camera);
		const last = current?.at(-1);
		if (
			current &&
			last &&
			startOf(clip) - endOf(last) <= gap &&
			localDay(clip.start) === localDay(current[0].start)
		)
			current.push(clip);
		else {
			const next = [clip];
			open.set(clip.camera, next);
			groups.push(next);
		}
	}
	return groups.map(toEvent).sort((a, b) => b.end - a.end || b.start - a.start);
}

function toEvent(clips: Recording[]): ClipEvent {
	const counts = new Map<string, number>();
	for (const c of clips) counts.set(c.trigger, (counts.get(c.trigger) ?? 0) + 1);
	return {
		id: clips[0].id,
		camera: clips[0].camera,
		day: localDay(clips[0].start),
		clips,
		start: startOf(clips[0]),
		end: Math.max(...clips.map(endOf)),
		triggers: [...counts].sort((a, b) => b[1] - a[1]),
		seconds: clips.reduce((sum, c) => sum + (c.duration ?? 0), 0),
		pinned: clips.filter((c) => c.pinned).length
	};
}

export interface HeatMap {
	/** The start of each hour (ms), oldest first; the last one holds `now`. */
	hours: number[];
	rows: { camera: string; counts: number[] }[];
	max: number;
}

/** Clips per camera and hour, for the `hours` hours up to `now`. */
export function heatMap(clips: Recording[], cameras: string[], now: number, hours = 24): HeatMap {
	const top = new Date(now);
	top.setMinutes(0, 0, 0);
	const first = top.getTime() - (hours - 1) * 3_600_000;
	const starts = Array.from({ length: hours }, (_, i) => first + i * 3_600_000);
	const rows = cameras.map((camera) => ({ camera, counts: Array<number>(hours).fill(0) }));
	const index = new Map(rows.map((r, i) => [r.camera, i]));
	let max = 0;
	for (const clip of clips) {
		const row = index.get(clip.camera);
		const hour = Math.floor((startOf(clip) - first) / 3_600_000);
		if (row === undefined || hour < 0 || hour >= hours) continue;
		max = Math.max(max, ++rows[row].counts[hour]);
	}
	return { hours: starts, rows, max };
}

/** "50 s", "26 min", "2 h 5 min": how much video, in words. */
export function videoLength(seconds: number): string {
	if (seconds < 60) return `${Math.round(seconds)} s`;
	const minutes = Math.round(seconds / 60);
	if (minutes < 60) return `${minutes} min`;
	const h = Math.floor(minutes / 60);
	return minutes % 60 ? `${h} h ${minutes % 60} min` : `${h} h`;
}
