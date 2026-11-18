// The app's shared state: the cameras, the server info, the live event stream, and toasts.
import {
	api,
	onUnauthorized,
	type AuthStatus,
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
import { readStoredJson, writeStored } from './stored';

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
	'away.changed',
	'mqtt.changed'
]);

export interface CameraControls {
	controls: Control[];
	presets: Preset[];
}

const CONTROLS_KEY = 'norn.controls';

class Store {
	cameras = $state<Camera[]>([]);
	circles = $state<Circle[]>([]);
	/** What cameras detect, under Norn's names, from the server. */
	labels = $state<Label[]>([]);
	// The controls of each camera, kept between visits (and reloads), so a camera page opens
	// complete and then updates in place.
	controls = $state<Record<string, CameraControls>>(readStoredJson(CONTROLS_KEY, {}));
	info = $state<Info | null>(null);
	/** Sign-in: on or off, and who is signed in here; null until asked. */
	auth = $state<AuthStatus | null>(null);
	connected = $state(false);
	loaded = $state(false);
	toasts = $state<Toast[]>([]);

	#listeners = new Set<Listener>();
	#retry = 1000;
	#refreshTimer: ReturnType<typeof setTimeout> | undefined;
	#nextToast = 1;
	#started = false;
	#refreshes = 0; // a response older than the newest request is dropped

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

	/** Everything may be changed here: an admin is signed in, or sign-in is off. */
	get isAdmin(): boolean {
		return !this.auth?.enabled || this.auth.user?.role === 'admin';
	}

	/** Sign-in is on and nobody is signed in here: the app shows the sign-in page. */
	get signedOut(): boolean {
		return !!this.auth?.enabled && !this.auth.user;
	}

	start() {
		if (this.#started) return;
		this.#started = true;
		onUnauthorized(() => this.#lostSession());
		this.#begin();
	}

	async #begin() {
		try {
			this.auth = await api.auth();
		} catch {
			this.auth = { enabled: false, user: null }; // an older server: no sign-in
		}
		if (this.signedOut) {
			this.loaded = true;
			return;
		}
		this.refresh();
		this.#connect();
	}

	/** Signed in (or sign-in turned on by the first user): load everything. */
	signedIn(user: { name: string; role: 'admin' | 'viewer' }) {
		this.auth = { enabled: true, user };
		this.refresh();
		if (!this.#socket) this.#connect();
	}

	async signOut() {
		await api.logout().catch(() => null);
		this.#forget();
		this.auth = { enabled: true, user: null };
	}

	#lostSession() {
		if (this.signedOut) return;
		this.#forget();
		this.auth = { enabled: true, user: null };
	}

	/** Nothing of this user's stays in the browser for the next one. */
	#forget() {
		this.#socket?.close();
		this.#socket = null;
		this.cameras = [];
		this.circles = [];
		this.info = null;
		this.controls = {};
		writeStored(CONTROLS_KEY, '{}');
	}

	async refresh() {
		const mine = ++this.#refreshes;
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
			if (mine !== this.#refreshes) return;
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
			writeStored(CONTROLS_KEY, JSON.stringify(this.controls));
		} catch {
			// keep what we had
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

	#socket: WebSocket | null = null;

	#connect() {
		if (this.signedOut) return;
		const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/events`;
		const socket = new WebSocket(url);
		this.#socket = socket;
		let opened = false;
		socket.onopen = () => {
			opened = true;
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
					const by = { ...events.by };
					const sources = event.data.sources as string[] | undefined;
					if (event.data.active && sources?.length) by[kind] = sources;
					else delete by[kind];
					events.by = by;
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
		socket.onclose = (e) => {
			this.connected = false;
			if (this.#socket !== socket) return; // signed out: closed on purpose
			this.#socket = null;
			if (e.code === 4401) return this.#lostSession(); // the session ended
			// Refused before it opened: a browser only sees that it failed. Signed out meanwhile?
			if (!opened)
				api
					.auth()
					.then((a) => a.enabled && !a.user && this.#lostSession())
					.catch(() => null);
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
