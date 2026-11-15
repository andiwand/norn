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

export function formatTime(iso: string): string {
	return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
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
	manual: 'Manual',
	motion: 'Motion',
	webhook: 'Webhook'
};

export function triggerLabel(trigger: string): string {
	return triggerLabels[trigger] ?? trigger.charAt(0).toUpperCase() + trigger.slice(1);
}
