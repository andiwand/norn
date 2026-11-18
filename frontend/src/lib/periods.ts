// The recent periods that cards ending now can show (a camera's activity, the heat map of the
// recordings): the same names and one remembered choice everywhere.
import { readStoredJson, writeStored } from './stored';

export const RECENT = [
	[1, 'Day'],
	[3, '3 days'],
	[7, 'Week']
] as const;
export type RecentDays = (typeof RECENT)[number][0];

/** "the last day", "the last 3 days", "the last week". */
export function recentText(days: RecentDays): string {
	return days === 1 ? 'the last day' : days === 7 ? 'the last week' : `the last ${days} days`;
}

const KEY = 'norn.recent-days';
export function readRecentDays(): RecentDays {
	const stored = readStoredJson<number>(KEY, 1);
	return RECENT.find(([d]) => d === stored)?.[0] ?? 1;
}
export function writeRecentDays(days: RecentDays) {
	writeStored(KEY, JSON.stringify(days));
}
