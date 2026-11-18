import { describe, expect, it } from 'vitest';
import { formatBytes, formatDay, formatDuration, serverTime, slugify } from './format';
import { errorText } from './api';

describe('format', () => {
	it('formats bytes', () => {
		expect(formatBytes(512)).toBe('512 B');
		expect(formatBytes(1_500_000)).toBe('1.5 MB');
		expect(formatBytes(42_000_000_000)).toBe('42 GB');
	});

	it('reads times on the server clock', () => {
		expect(serverTime('2026-11-15T12:00', 60)).toBe(Date.UTC(2026, 10, 15, 11));
		expect(serverTime('2026-11-15T12:00:30', -300)).toBe(Date.UTC(2026, 10, 15, 17, 0, 30));
	});

	it('formats durations', () => {
		expect(formatDuration(null)).toBe('');
		expect(formatDuration(5)).toBe('0:05');
		expect(formatDuration(3725)).toBe('1:02:05');
	});

	it('names days relative to today', () => {
		const today = new Date(2026, 10, 15, 12);
		expect(formatDay('2026-11-15', today)).toBe('Today');
		expect(formatDay('2026-11-14', today)).toBe('Yesterday');
		expect(formatDay('2026-11-01', today)).not.toBe('Today');
	});

	it('makes camera ids', () => {
		expect(slugify('Front Door')).toBe('front-door');
		expect(slugify('  Garten – Süd! ')).toBe('garten-sud');
		expect(slugify('Straße')).toBe('strasse');
	});
});

describe('errorText', () => {
	it('reads FastAPI errors', () => {
		expect(errorText('nope')).toBe('nope');
		expect(errorText([{ loc: ['body', 'url'], msg: 'bad' }])).toBe('url: bad');
		expect(errorText(42)).toBeUndefined();
	});
});
