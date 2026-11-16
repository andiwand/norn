// The app's shared state: the cameras, the server info, the live event stream, and toasts.
import {
	api,
	type Camera,
	type Circle,
	type Control,
	type Info,
	type Label,
	type NornEvent,
	type Preset,
	type Recording
} from './api';
import { setLabels } from './format';

export interface Toast {
	id: number;
	message: string;
	kind: 'info' | 'error' | 'success';
}

type Listener = (event: NornEvent) => void;

// Events after which the camera list (and its recording badges) must be loaded again.
const REFRESH = new Set([
	'cameras.changed',
	'recording.started',
	'recording.finished',
	'recording.continuous',
	'go2rtc.ready',
	'camera.device',
	'settings.changed',
	'away.changed'
]);

export interface CameraControls {
	controls: Control[];
	presets: Preset[];
}

const CONTROLS_KEY = 'norn.controls';

function loadCachedControls(): Record<string, CameraControls> {
	try {
		return JSON.parse(localStorage.getItem(CONTROLS_KEY) ?? '{}');
	} catch {
		return {};
	}
}

class Store {
	cameras = $state<Camera[]>([]);
	circles = $state<Circle[]>([]);
	/** What cameras detect, under Norn's names, from the server. */
	labels = $state<Label[]>([]);
	// The controls of each camera, kept between visits (and reloads), so a camera page opens
	// complete and then updates in place.
	controls = $state<Record<string, CameraControls>>(loadCachedControls());
	info = $state<Info | null>(null);
	connected = $state(false);
	loaded = $state(false);
	toasts = $state<Toast[]>([]);

	#listeners = new Set<Listener>();
	#socket: WebSocket | null = null;
	#retry = 1000;
	#refreshTimer: ReturnType<typeof setTimeout> | undefined;
	#nextToast = 1;
	#started = false;

	#takeLabels(labels: Label[]) {
		setLabels(labels);
		this.labels = labels;
	}

	camera(id: string): Camera | undefined {
		return this.cameras.find((c) => c.id === id);
	}

	circle(id: string): Circle | undefined {
		return this.circles.find((c) => c.id === id);
	}

	start() {
		if (this.#started) return;
		this.#started = true;
		this.refresh();
		this.#connect();
	}

	async refresh() {
		try {
			const [cameras, info, circles] = await Promise.all([
				api.cameras(),
				api.info(),
				api.circles(),
				this.labels.length
					? null
					: api
							.labels()
							.then((l) => this.#takeLabels(l))
							.catch(() => null) // the names fall back to the ids
			]);
			this.cameras = cameras;
			this.circles = circles;
			this.info = info;
			// Fetch the controls of cameras not seen before, so their pages open complete too.
			for (const camera of cameras) {
				if (camera.enabled && !(camera.id in this.controls)) this.loadControls(camera.id);
			}
		} catch (e) {
			console.warn('refresh failed', e);
		} finally {
			this.loaded = true;
		}
	}

	async loadControls(id: string, fresh = false) {
		try {
			const data = await api.controls(id, fresh);
			this.controls[id] = data;
			this.#saveControls();
		} catch {
			// keep what we had
		}
	}

	#saveControls() {
		try {
			localStorage.setItem(CONTROLS_KEY, JSON.stringify(this.controls));
		} catch {
			// private mode or full storage: the cache is only a convenience
		}
	}

	/** Listen to server events. Returns the function that stops listening. */
	on(listener: Listener): () => void {
		this.#listeners.add(listener);
		return () => this.#listeners.delete(listener);
	}

	toast(message: string, kind: Toast['kind'] = 'info', ms = 4000) {
		const id = this.#nextToast++;
		this.toasts.push({ id, message, kind });
		setTimeout(() => this.dismiss(id), ms);
	}

	dismiss(id: number) {
		this.toasts = this.toasts.filter((t) => t.id !== id);
	}

	/** Pin or unpin a recording; the new state, or undefined when it failed. */
	pin(recording: Recording, pinned: boolean) {
		return this.attempt(
			() => api.pinRecording(recording.id, pinned),
			pinned ? 'Pinned: Norn keeps it' : 'Unpinned'
		);
	}

	/** Run an API call; show its error as a toast instead of throwing. */
	async attempt<T>(fn: () => Promise<T>, success?: string): Promise<T | undefined> {
		try {
			const result = await fn();
			if (success) this.toast(success, 'success');
			return result;
		} catch (e) {
			this.toast(e instanceof Error ? e.message : String(e), 'error', 6000);
			return undefined;
		}
	}

	#connect() {
		const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/events`;
		const socket = new WebSocket(url);
		this.#socket = socket;
		socket.onopen = () => {
			this.connected = true;
			this.#retry = 1000;
			this.refresh(); // catch up on what happened while disconnected
		};
		socket.onmessage = (message) => {
			const event = JSON.parse(message.data) as NornEvent;
			if (REFRESH.has(event.type)) this.#scheduleRefresh();
			const camera = typeof event.data.camera === 'string' ? event.data.camera : null;
			if (camera && event.type === 'camera.controls' && camera in this.controls) {
				this.loadControls(camera);
			}
			if (camera && event.type === 'camera.event') {
				// Live, without loading all cameras again.
				const events = this.camera(camera)?.events;
				const kind = String(event.data.kind);
				if (events) {
					events.active = event.data.active
						? [...new Set([...events.active, kind])]
						: events.active.filter((k) => k !== kind);
				}
			}
			if (camera && event.type === 'camera.control') {
				const control = this.controls[camera]?.controls.find((c) => c.id === event.data.control);
				if (control && control.kind !== 'button') control.value = event.data.value;
			}
			if (event.type === 'config.error')
				this.toast(`Config not loaded: ${event.data.error}`, 'error', 8000);
			for (const listener of this.#listeners) listener(event);
		};
		socket.onclose = () => {
			this.connected = false;
			this.#socket = null;
			setTimeout(() => this.#connect(), this.#retry);
			this.#retry = Math.min(this.#retry * 2, 15000);
		};
	}

	#scheduleRefresh() {
		clearTimeout(this.#refreshTimer);
		this.#refreshTimer = setTimeout(() => this.refresh(), 150);
	}
}

export const store = new Store();
