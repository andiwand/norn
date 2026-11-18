// The Norn API. The backend serves this app, so all calls are relative to its origin.

export type Capability =
	| 'live'
	| 'snapshot'
	| 'ptz'
	| 'presets'
	| 'controls'
	| 'audio'
	| 'talkback'
	| 'firmware-upload'
	| 'firmware-online'
	| 'events'
	| 'preset-save';

export interface StreamInfo {
	id: string;
	label: string;
	name: string;
	codec: string | null;
	/** Made by Norn for weak connections (FFmpeg runs only while someone watches). */
	transcoded?: boolean;
	width?: number | null;
	height?: number | null;
	fps?: number | null;
}

export interface StreamProbe {
	ok: boolean;
	width: number | null;
	height: number | null;
	codec: string | null;
	fps: number | null;
	error: string | null;
}

/** A named view: one of the camera's preset slots, and settings to apply there. */
export interface NornPreset {
	name: string;
	slot: string;
	controls: Record<string, unknown>;
	/** What records while the camera is here; null: the camera's setting. */
	triggers: string[] | null;
	clip_seconds: number | null;
	prebuffer_seconds: number | null;
}

export type PresetRecording = Pick<NornPreset, 'triggers' | 'clip_seconds' | 'prebuffer_seconds'>;

export interface Patrol {
	enabled: boolean;
	presets: string[];
	order: 'sequence' | 'random';
	dwell_seconds: number;
	schedule: Window[];
	pause_after_manual: number;
}

/** When `cameras` (empty: this one) detect one of `kinds`, turn to one of `presets`. */
export interface Reaction {
	kinds: string[];
	cameras: string[];
	presets: string[];
	hold_seconds: number;
}

/** A stream the camera may have, to switch on or off; `probe`: what testing it found. */
export interface StreamOption {
	id: string;
	label: string;
	active: boolean;
	probe: StreamProbe | null;
	/** Kept ready from its newest keyframe: live video starts at once. */
	ready: boolean;
	/** Whether it can be (not MJPEG, not made by FFmpeg). */
	can_be_ready: boolean;
}

export interface DeviceInfo {
	online: boolean;
	error: string | null;
	manufacturer: string | null;
	model: string | null;
	firmware: string | null;
	hardware: string | null;
	serial: string | null;
	mac: string | null;
	name: string | null;
	details: Record<string, string>;
	notes: string[];
}

export interface FirmwareStatus {
	status: 'current' | 'update' | 'end-of-life' | 'unknown';
	current: string | null;
	latest: string | null;
	released: string | null;
	url: string | null;
	checked: string | null;
	notes: string[];
}

export interface FirmwareUpdate {
	state: 'running' | 'done' | 'failed';
	error?: string;
	source?: 'file' | 'online';
}

export interface Camera {
	id: string;
	name: string;
	driver: string;
	enabled: boolean;
	record: 'off' | 'continuous';
	/** The driver options, without passwords (addresses show them as •••). */
	options: Record<string, unknown>;
	/** Which secret options are set (their values never leave the server). */
	secrets: string[];
	error: string | null;
	capabilities: Capability[];
	streams: StreamInfo[];
	recording: {
		mode: 'clip' | 'continuous';
		trigger?: string;
		start?: string;
		seconds?: number;
	} | null;
	auto_update: boolean;
	/** Overrides of the global recording settings; null: the global value. */
	picture_seconds: number | null;
	prebuffer_seconds: number | null;
	clip_seconds: number | null;
	/** What the camera detects that starts a clip; null: as its circle or the settings say. */
	triggers: string[] | null;
	schedule: Window[] | null;
	detection: Partial<DetectionSettings> | null;
	/** The streams Norn uses, by id; null: all that work. */
	stream_selection?: string[] | null;
	ready_streams?: string[] | null;
	stream_options: StreamOption[];
	/** Norn's presets (by id), patrol, reactions to detections, following. */
	presets_norn: Record<string, NornPreset>;
	patrol: Patrol | null;
	/** The Norn preset it returns to when nothing else steers it. */
	default_preset: string | null;
	reactions: Reaction[];
	follow: 'off' | 'always' | 'recording' | 'away';
	/** The camera's own web page, when it answers. */
	web_url: string | null;
	/** The camera serves its streams at the same time (null: not known). */
	concurrent: boolean | null;
	/** What the camera can detect (by itself, and by Norn), and what it detects now. */
	events: {
		kinds: string[];
		camera: string[];
		norn: string[];
		active: string[];
		detect_ms: number | null;
	} | null;
	/** Seconds of the past a clip started now would include (the RAM buffer). */
	buffered: number;
	device: DeviceInfo | null;
	firmware: FirmwareStatus | null;
	update: FirmwareUpdate | null;
}

export interface Circle {
	id: string;
	name: string;
	cameras: string[];
	picture_seconds: number | null;
	prebuffer_seconds: number | null;
	clip_seconds: number | null;
	triggers: string[] | null;
	schedule: Window[] | null;
	/** When one camera detects a trigger, all cameras of the circle record. */
	together: boolean;
	detection?: Partial<DetectionSettings> | null;
}

/** A control all cameras of a circle share. `mixed`: the cameras have different values. */
export type CircleControl = Control & { mixed: boolean };

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
	kind: 'video' | 'picture';
	start: string;
	trigger: string;
	size: number;
	duration: number | null;
	thumbnail: boolean;
	/** When Norn deletes it; null: kept until someone deletes it. */
	expires: string | null;
	/** Kept until someone unpins it, whatever the limits. */
	pinned: boolean;
	/** Still being recorded (a continuous file in the temporary storage). */
	live?: boolean;
	meta: Record<string, unknown>;
}

export interface MqttStatus {
	enabled: boolean;
	connected?: boolean;
	broker?: string;
	prefix?: string;
	discovery?: string | null;
	stills?: number;
	/** Why the last connection failed. */
	error?: string | null;
	/** When it connected, or failed (seconds since the epoch). */
	since?: number | null;
	/** The last command from MQTT that failed. */
	last_error?: { command: string; error: string; time: string } | null;
}

export interface Info {
	version: string;
	config_error: string | null;
	config_path: string;
	/** The server's clock: schedules and away times follow it. */
	time: { zone: string; offset_minutes: number };
	go2rtc: { running: boolean; version?: string };
	/** Norn's RTSP server; `shared`: other devices on the network can play it. */
	rtsp: { port: number; shared: boolean };
	recording_available: boolean;
	recording: RecordingSettings;
	/** MQTT, for Home Assistant: off unless NORN_MQTT is set. */
	mqtt: MqttStatus;
	/** Away mode: `now` is whether it is on at the moment (switched on, or planned). */
	away: AwaySettings & { now: boolean };
	detection: DetectionSettings & {
		objects_unavailable: string | null;
		models: Record<string, string>;
	};
}

/** A time of the week; `to` before `from` runs past midnight. */
export interface Window {
	days: string[];
	from: string;
	to: string;
}

export interface DetectionSettings {
	stills: 'auto' | 'keyframe' | 'live';
	motion: boolean;
	objects: boolean;
	every_seconds: number;
	sensitivity: number;
	min_score: number;
	model: 'nano' | 'tiny';
}

/** What cameras detect, under Norn's names (GET /api/labels). */
export interface Label {
	id: string;
	name: string;
	description: string;
}

export interface AwaySettings {
	active: boolean;
	start: string | null;
	end: string | null;
	triggers: string[];
	picture_seconds: number;
}

export interface RecordingSettings {
	retention_days: number;
	max_gb: number;
	min_free_gb: number;
	segment_minutes: number;
	clip_seconds: number;
	prebuffer_seconds: number;
	picture_seconds: number;
	triggers: string[];
	schedule: Window[];
}

export interface SettingsValues {
	recording: RecordingSettings;
	firmware: { check_hours: number };
	away: AwaySettings;
	detection: DetectionSettings;
}

export interface StorageStage {
	path: string;
	used: number;
	files: number;
	total: number | null;
	free: number | null;
	/** On a tmpfs (RAM) rather than a disk. */
	ram: boolean;
}

export interface ResourceProcess {
	pid: number;
	kind: string;
	camera: string | null;
	/** Percent of one core. */
	cpu: number;
	memory: number;
}

export interface Resources {
	cpu: number;
	memory: number;
	processes: ResourceProcess[];
	system: { cores: number; cpu: number; memory_total: number; memory_available: number };
	gpu: { used: boolean; available: string[] };
}

export interface ForecastCamera {
	camera: string;
	per_day: number;
	steady: number | null;
	count_per_day: number;
	basis: 'measured' | 'estimated';
}

export interface ForecastTrigger {
	trigger: string;
	per_day: number;
	/** What it holds once it levels off; null: it only grows (kept, or no retention). */
	steady: number | null;
	kept: boolean;
	cameras: ForecastCamera[];
}

export interface Forecast {
	retention_days: number;
	per_day: number;
	steady: number;
	growing_per_day: number;
	days_until_full: number | null;
	/** Bytes until the size or free-space limit; null: no limit set. */
	limit: number | null;
	days_until_limit: number | null;
	triggers: ForecastTrigger[];
}

export interface LogLine {
	id: number;
	time: number;
	level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';
	logger: string;
	message: string;
}

export interface Storage {
	buffer: StorageStage;
	temp: StorageStage;
	recordings: StorageStage;
}

export interface SettingsData {
	values: SettingsValues;
	defaults: SettingsValues;
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

/** A query string of the parameters that are set. */
function query(params: Record<string, string | number | undefined>): string {
	return new URLSearchParams(
		Object.entries(params)
			.filter(([, v]) => v !== undefined && v !== '')
			.map(([k, v]) => [k, String(v)])
	).toString();
}

export const api = {
	info: () => request<Info>('GET', '/info'),
	settings: () => request<SettingsData>('GET', '/settings'),
	/** Fields left out keep their value. */
	saveSettings: (values: { [K in keyof SettingsValues]?: Partial<SettingsValues[K]> }) =>
		request<SettingsData>('PUT', '/settings', values),
	drivers: () => request<Driver[]>('GET', '/drivers'),
	labels: () => request<Label[]>('GET', '/labels'),
	cameras: () => request<Camera[]>('GET', '/cameras'),
	addCamera: (body: Record<string, unknown>) => request<Camera>('POST', '/cameras', body),
	updateCamera: (id: string, body: Record<string, unknown>) =>
		request<Camera>('PUT', `/cameras/${enc(id)}`, body),
	deleteCamera: (id: string) => request<void>('DELETE', `/cameras/${enc(id)}`),
	orderCameras: (ids: string[]) => request<Camera[]>('PUT', '/camera-order', { ids }),
	controls: (id: string, fresh = false) =>
		request<{ controls: Control[]; presets: Preset[] }>(
			'GET',
			`/cameras/${enc(id)}/controls${fresh ? '?fresh=true' : ''}`
		),
	setControl: (id: string, control: string, value: unknown) =>
		request<{ ok: boolean }>('POST', `/cameras/${enc(id)}/controls/${enc(control)}`, { value }),
	ptz: (id: string, command: PtzCommand) =>
		request<{ ok: boolean }>('POST', `/cameras/${enc(id)}/ptz`, command),
	record: (id: string, seconds?: number) =>
		request<unknown>('POST', `/cameras/${enc(id)}/record`, { trigger: 'manual', seconds }),
	stopRecord: (id: string) => request<unknown>('DELETE', `/cameras/${enc(id)}/record`),
	storage: () => request<Storage>('GET', '/storage'),
	resources: () => request<Resources>('GET', '/resources'),
	logs: (params: { level?: string; after?: number; text?: string; limit?: number } = {}) =>
		request<{ lines: LogLine[]; file: string | null }>('GET', `/logs?${query(params)}`),
	forecast: () => request<Forecast>('GET', '/forecast'),
	recordings: (
		params: {
			camera?: string;
			day?: string;
			limit?: number;
			since?: string;
			until?: string;
			kind?: 'video' | 'picture';
			/** A trigger, or `clips`: videos a trigger started. */
			trigger?: string;
			/** Thin the pictures to about this many per camera. */
			pictures?: number;
		} = {}
	) =>
		request<{ recordings: Recording[]; days: string[]; truncated: boolean }>(
			'GET',
			`/recordings?${query(params)}`
		),
	deleteRecording: (id: string) => request<void>('DELETE', `/recordings/${id}`),
	pinRecording: (id: string, pinned: boolean) =>
		request<Recording>('PUT', `/recordings/${id}/pin`, { pinned }),
	circles: () => request<Circle[]>('GET', '/circles'),
	addCircle: (body: Circle) => request<Circle>('POST', '/circles', body),
	updateCircle: (id: string, body: Omit<Circle, 'id'>) =>
		request<Circle>('PUT', `/circles/${enc(id)}`, body),
	deleteCircle: (id: string) => request<void>('DELETE', `/circles/${enc(id)}`),
	circleControls: (id: string) =>
		request<{ controls: CircleControl[] }>('GET', `/circles/${enc(id)}/controls`),
	setCircleControl: (id: string, control: string, value: unknown) =>
		request<{ ok: boolean; errors: Record<string, string> }>(
			'POST',
			`/circles/${enc(id)}/controls/${enc(control)}`,
			{ value }
		),
	recordCircle: (id: string) =>
		request<{ clips: unknown[]; errors: Record<string, string> }>(
			'POST',
			`/circles/${enc(id)}/record`,
			{ trigger: 'manual' }
		),
	stopCircle: (id: string) => request<unknown>('DELETE', `/circles/${enc(id)}/record`),
	savePreset: (id: string, preset: string, body: { name: string; controls: string[] }) =>
		request<NornPreset>('PUT', `/cameras/${enc(id)}/presets/${enc(preset)}`, body),
	setPresetRecording: (id: string, preset: string, body: PresetRecording) =>
		request<NornPreset>('PUT', `/cameras/${enc(id)}/presets/${enc(preset)}/recording`, body),
	setDefaultPreset: (id: string, preset: string | null) =>
		request<Camera>('PUT', `/cameras/${enc(id)}/default-preset`, { preset }),
	deletePreset: (id: string, preset: string) =>
		request<void>('DELETE', `/cameras/${enc(id)}/presets/${enc(preset)}`),
	gotoPreset: (id: string, preset: string) =>
		request<void>('POST', `/cameras/${enc(id)}/presets/${enc(preset)}/goto`),
	probeStreams: (id: string) => request<Camera>('POST', `/cameras/${enc(id)}/streams/probe`),
	refreshDevice: (id: string) => request<Camera>('POST', `/cameras/${enc(id)}/device`),
	updateFirmware: async (id: string, file?: File): Promise<Camera> => {
		const response = await fetch(`/api/cameras/${enc(id)}/firmware`, {
			method: 'POST',
			headers: file ? { 'Content-Type': 'application/octet-stream' } : {},
			body: file ?? undefined
		});
		if (!response.ok) {
			const data = await response.json().catch(() => ({}));
			throw new ApiError(response.status, errorText(data.detail) ?? response.statusText);
		}
		return response.json();
	}
};

/** The body of a camera for PUT /cameras/{id}: its config, with one field changed. */
export function cameraBody(camera: Camera, change: Record<string, unknown> = {}) {
	return {
		name: camera.name,
		driver: camera.driver,
		enabled: camera.enabled,
		record: camera.record,
		auto_update: camera.auto_update,
		picture_seconds: camera.picture_seconds,
		prebuffer_seconds: camera.prebuffer_seconds,
		clip_seconds: camera.clip_seconds,
		triggers: camera.triggers,
		schedule: camera.schedule,
		detection: camera.detection,
		streams: camera.stream_selection ?? null,
		ready_streams: camera.ready_streams ?? null,
		...camera.options,
		...change
	};
}

export const urls = {
	stream: (camera: string, stream = 'main') =>
		`/api/stream?camera=${enc(camera)}&stream=${enc(stream)}`,
	presetPicture: (camera: string, preset: string, version = 0) =>
		`/api/cameras/${enc(camera)}/presets/${enc(preset)}.jpg?v=${version}`,
	/** The newest still, at once (for a picture before the video plays). */
	still: (camera: string, maxAge = 15) =>
		`/api/cameras/${enc(camera)}/still.jpg?max_age=${maxAge}&t=${Date.now()}`,
	snapshot: (camera: string, stream = 'main') =>
		`/api/cameras/${enc(camera)}/snapshot?stream=${enc(stream)}&t=${Date.now()}`,
	recording: (r: Recording) => `/api/recordings/${r.id}`,
	/** A video's frame `seconds` in, small, for scrubbing the timeline. */
	frame: (r: Recording, seconds: number) => `/api/recordings/${r.id}/frame?at=${seconds}`,
	/** A small image for lists: a picture's small copy, or the video's thumbnail. */
	small: (r: Recording) =>
		r.kind === 'picture'
			? `/api/recordings/${r.id}?small=true`
			: `/api/recordings/${r.id.replace(/\.mp4$/, '.jpg')}`
};
