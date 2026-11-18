// Formatting helpers for the UI.

export function formatBytes(bytes: number): string {
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	let value = bytes;
	let unit = 0;
	while (value >= 1000 && unit < units.length - 1) {
		value /= 1000;
		unit++;
	}
	return `${value.toFixed(value < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`;
}

export function formatDuration(seconds: number | null): string {
	if (seconds === null || !Number.isFinite(seconds)) return '';
	const s = Math.round(seconds);
	const h = Math.floor(s / 3600);
	const m = Math.floor((s % 3600) / 60);
	const rest = String(s % 60).padStart(2, '0');
	return h ? `${h}:${String(m).padStart(2, '0')}:${rest}` : `${m}:${rest}`;
}

/** A time left, roughly: "3 days", "5 h", "20 min". */
export function formatRemaining(ms: number): string {
	const minutes = Math.max(0, Math.round(ms / 60_000));
	if (minutes < 60) return `${minutes} min`;
	const hours = Math.round(minutes / 60);
	if (hours < 48) return `${hours} h`;
	return `${Math.round(hours / 24)} days`;
}

/** "every 30 seconds", "every 5 minutes", "every hour"; "off" for 0. */
export function formatInterval(seconds: number): string {
	if (!seconds) return 'off';
	for (const [unit, size] of [
		['hour', 3600],
		['minute', 60]
	] as const) {
		if (seconds % size === 0) {
			const n = seconds / size;
			return n === 1 ? `every ${unit}` : `every ${n} ${unit}s`;
		}
	}
	return `every ${seconds} seconds`;
}

export function formatTime(iso: string): string {
	return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/** The moment (ms) of a time without a zone on the server's clock (`offsetMinutes` east of UTC),
 * like away mode's start and end: the browser may be in another zone. */
export function serverTime(local: string, offsetMinutes: number): number {
	const [date, time = '00:00'] = local.split('T');
	const [y, mo, d] = date.split('-').map(Number);
	const [h, mi, s = 0] = time.split(':').map(Number);
	return Date.UTC(y, mo - 1, d, h, mi, Math.floor(s)) - offsetMinutes * 60_000;
}

/** The browser's day (YYYY-MM-DD) of a moment, to group times shown in the browser's zone. */
export function localDay(iso: string): string {
	const t = new Date(iso);
	const pad = (n: number) => String(n).padStart(2, '0');
	return `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`;
}

/** "Today", "Yesterday", or a date like "Fri, Nov 13", for a YYYY-MM-DD day. */
export function formatDay(day: string, today = new Date()): string {
	const [y, m, d] = day.split('-').map(Number);
	const date = new Date(y, m - 1, d);
	const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
	const diff = Math.round((start.getTime() - date.getTime()) / 86_400_000);
	if (diff === 0) return 'Today';
	if (diff === 1) return 'Yesterday';
	return date.toLocaleDateString([], {
		weekday: 'short',
		month: 'short',
		day: 'numeric',
		year: date.getFullYear() === today.getFullYear() ? undefined : 'numeric'
	});
}

/** Controls by their group, in the order the groups first appear. */
export function byGroup<T extends { group: string }>(controls: T[]): [string, T[]][] {
	const groups: Record<string, T[]> = {};
	for (const c of controls) (groups[c.group] ??= []).push(c);
	return Object.entries(groups);
}

/** What a camera is: "Reolink E1 Zoom", else its driver. */
export function cameraModel(c: {
	driver: string;
	device: { manufacturer: string | null; model: string | null } | null;
}): string {
	return [c.device?.manufacturer, c.device?.model].filter(Boolean).join(' ') || c.driver;
}

/** A camera id from a name: "Front Door" -> "front-door". */
export function slugify(name: string): string {
	return name
		.toLowerCase()
		.normalize('NFKD')
		.replace(/[̀-ͯ]/g, '')
		.replace(/ß/g, 'ss')
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-+|-+$/g, '')
		.slice(0, 63);
}

export const triggerLabels: Record<string, string> = {
	continuous: 'Continuous',
	interval: 'Picture',
	manual: 'Manual',
	webhook: 'Webhook'
};

export function triggerLabel(trigger: string): string {
	return triggerLabels[trigger] ?? trigger.charAt(0).toUpperCase() + trigger.slice(1);
}

/** Take the labels from the server (labels.py): their names become the names of those triggers. */
export function setLabels(labels: { id: string; name: string }[]) {
	for (const label of labels) triggerLabels[label.id] = label.name;
}

/** A number field's value, or null when it's empty (the setting from above). */
export function numberOrNull(value: number | null | undefined): number | null {
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** What a circle, camera or preset sets itself, in a few words each. */
export function ownSettings(x: {
	triggers?: string[] | null;
	schedule?: { from: string; to: string }[] | null;
	clip_seconds?: number | null;
	prebuffer_seconds?: number | null;
	picture_seconds?: number | null;
	detection?: object | null;
}): string[] {
	const parts: string[] = [];
	if (x.triggers != null)
		parts.push(x.triggers.length ? x.triggers.map(triggerLabel).join(', ') : 'no detections');
	if (x.schedule != null)
		parts.push(
			x.schedule.length ? x.schedule.map((w) => `${w.from}–${w.to}`).join(', ') : 'any time'
		);
	if (x.clip_seconds != null) parts.push(`${x.clip_seconds} s clips`);
	if (x.prebuffer_seconds != null) parts.push(`${x.prebuffer_seconds} s before`);
	if (x.picture_seconds != null)
		parts.push(x.picture_seconds ? `pictures ${formatInterval(x.picture_seconds)}` : 'no pictures');
	if (x.detection && Object.keys(x.detection).length) parts.push('own detection');
	return parts;
}
