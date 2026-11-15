// The Norn API. The backend serves this app, so all calls are relative to its origin.

export type Capability =
	'live' | 'snapshot' | 'ptz' | 'presets' | 'controls' | 'audio' | 'talkback';

export interface StreamInfo {
	id: string;
	label: string;
	name: string;
}

export interface Camera {
	id: string;
	name: string;
	driver: string;
	enabled: boolean;
	record: 'off' | 'continuous';
	options: Record<string, unknown>;
	error: string | null;
	capabilities: Capability[];
	streams: StreamInfo[];
	recording: {
		mode: 'clip' | 'continuous';
		trigger?: string;
		start?: string;
		seconds?: number;
	} | null;
}

export interface ControlOption {
	value: string;
	label: string;
}

export interface Control {
	id: string;
	label: string;
	kind: 'toggle' | 'select' | 'range' | 'button';
	group: string;
	value?: unknown;
	options?: ControlOption[];
	min?: number;
	max?: number;
	step?: number;
	unit?: string;
	icon?: string;
}

export interface Preset {
	id: string;
	name: string;
}

export interface JsonSchemaProperty {
	type?: string;
	title?: string;
	description?: string;
	default?: unknown;
	enum?: string[];
	pattern?: string;
	anyOf?: JsonSchemaProperty[];
	format?: string;
}

export interface Driver {
	name: string;
	label: string;
	description: string;
	options: { properties?: Record<string, JsonSchemaProperty>; required?: string[] };
}

export interface Recording {
	id: string;
	camera: string;
	day: string;
	name: string;
	start: string;
	trigger: string;
	size: number;
	duration: number | null;
	thumbnail: boolean;
	meta: Record<string, unknown>;
}

export interface Info {
	version: string;
	config_error: string | null;
	config_path: string;
	go2rtc: { running: boolean; version?: string };
	recording_available: boolean;
	recording: { retention_days: number; segment_minutes: number; clip_seconds: number };
}

export interface NornEvent {
	type: string;
	time: number;
	data: Record<string, unknown>;
}

export interface PtzCommand {
	action: 'move' | 'stop' | 'goto' | 'home';
	pan?: number;
	tilt?: number;
	zoom?: number;
	preset?: string;
}

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
	const response = await fetch(`/api${path}`, {
		method,
		headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	if (!response.ok) {
		let message = response.statusText;
		try {
			const data = await response.json();
			message = errorText(data.detail) ?? message;
		} catch {
			// not JSON
		}
		throw new ApiError(response.status, message);
	}
	if (response.status === 204) return undefined as T;
	return response.json() as Promise<T>;
}

/** FastAPI's `detail` is a string, or a list of validation errors. */
export function errorText(detail: unknown): string | undefined {
	if (typeof detail === 'string') return detail;
	if (Array.isArray(detail)) {
		return detail
			.map((e: { loc?: unknown[]; msg?: string }) => {
				const field = (e.loc ?? []).filter((p) => p !== 'body').join('.');
				return field ? `${field}: ${e.msg}` : e.msg;
			})
			.join('; ');
	}
	return undefined;
}

const enc = encodeURIComponent;

export const api = {
	info: () => request<Info>('GET', '/info'),
	drivers: () => request<Driver[]>('GET', '/drivers'),
	cameras: () => request<Camera[]>('GET', '/cameras'),
	camera: (id: string) => request<Camera>('GET', `/cameras/${enc(id)}`),
	addCamera: (body: Record<string, unknown>) => request<Camera>('POST', '/cameras', body),
	updateCamera: (id: string, body: Record<string, unknown>) =>
		request<Camera>('PUT', `/cameras/${enc(id)}`, body),
	deleteCamera: (id: string) => request<void>('DELETE', `/cameras/${enc(id)}`),
	controls: (id: string) =>
		request<{ controls: Control[]; presets: Preset[] }>('GET', `/cameras/${enc(id)}/controls`),
	setControl: (id: string, control: string, value: unknown) =>
		request<void>('POST', `/cameras/${enc(id)}/controls/${enc(control)}`, { value }),
	ptz: (id: string, command: PtzCommand) =>
		request<void>('POST', `/cameras/${enc(id)}/ptz`, command),
	record: (id: string, seconds?: number) =>
		request<unknown>('POST', `/cameras/${enc(id)}/record`, { trigger: 'manual', seconds }),
	stopRecord: (id: string) => request<unknown>('DELETE', `/cameras/${enc(id)}/record`),
	recordings: (params: { camera?: string; day?: string; limit?: number } = {}) => {
		const query = new URLSearchParams(
			Object.entries(params).filter(([, v]) => v !== undefined && v !== '') as [string, string][]
		);
		return request<{ recordings: Recording[]; days: string[] }>('GET', `/recordings?${query}`);
	},
	deleteRecording: (id: string) => request<void>('DELETE', `/recordings/${id}`)
};

export const urls = {
	stream: (camera: string, stream = 'main') =>
		`/api/stream?camera=${enc(camera)}&stream=${enc(stream)}`,
	snapshot: (camera: string, stream = 'main') =>
		`/api/cameras/${enc(camera)}/snapshot?stream=${enc(stream)}&t=${Date.now()}`,
	recording: (r: Recording) => `/api/recordings/${r.id}`,
	thumbnail: (r: Recording) => `/api/recordings/${r.id.replace(/\.mp4$/, '.jpg')}`
};
