// Notifications on this device (web push): whether it can get them, turning them on and off,
// and the devices that get them. The service worker (src/service-worker.ts) shows them.
import { api, type PushDevice } from './api';

/** Why this browser can't get notifications, or that it can. */
export type Support =
	| 'checking'
	| 'ok'
	/** Plain http on an address in the house: browsers allow push only over HTTPS. */
	| 'insecure'
	/** iPhone and iPad: only the app on the home screen gets notifications. */
	| 'ios-browser'
	| 'unsupported'
	/** The person said no: only the browser's site settings undo it. */
	| 'denied';

function isIos(): boolean {
	const ua = navigator.userAgent;
	return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}

function standalone(): boolean {
	return (
		matchMedia('(display-mode: standalone)').matches ||
		(navigator as Navigator & { standalone?: boolean }).standalone === true
	);
}

function support(): Support {
	if (!isSecureContext) return 'insecure';
	if (isIos() && !standalone()) return 'ios-browser';
	if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window))
		return 'unsupported';
	if (Notification.permission === 'denied') return 'denied';
	return 'ok';
}

/** The key as the bytes PushManager.subscribe() wants. */
function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
	const base64 = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4))
		.replace(/-/g, '+')
		.replace(/_/g, '/');
	const raw = atob(base64);
	const bytes = new Uint8Array(new ArrayBuffer(raw.length));
	for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
	return bytes;
}

async function registration(): Promise<ServiceWorkerRegistration> {
	// SvelteKit registers the service worker; in case it hasn't yet (or the page came before it).
	const existing = await navigator.serviceWorker.getRegistration('/');
	if (!existing)
		await navigator.serviceWorker.register('/service-worker.js', {
			type: import.meta.env.DEV ? 'module' : 'classic'
		});
	return navigator.serviceWorker.ready;
}

class Push {
	support = $state<Support>('checking');
	/** The devices this person sees: their own (an admin: everyone's). */
	devices = $state<PushDevice[]>([]);
	/** This browser's device, when it gets notifications. */
	device = $state<PushDevice | null>(null);
	busy = $state(false);
	#key = '';

	/** Look at this browser and the devices on the server. */
	async load() {
		this.support = support();
		const info = await api.notifications();
		this.#key = info.public_key;
		this.devices = info.devices;
		this.device = null;
		if (this.support !== 'ok') return;
		const subscription = await (await registration()).pushManager.getSubscription();
		if (!subscription) return;
		this.device = this.devices.find((d) => d.endpoint === subscription.endpoint) ?? null;
		// Subscribed, but Norn forgot it (the push service said it was gone, a new key): again.
		if (!this.device && Notification.permission === 'granted') {
			this.device = await api.addDevice(subscription.toJSON());
			this.devices = [...this.devices, this.device];
		}
	}

	/** Turn notifications on here: the browser asks the person first. */
	async enable(): Promise<void> {
		this.busy = true;
		try {
			const permission = await Notification.requestPermission();
			if (permission !== 'granted') {
				this.support = permission === 'denied' ? 'denied' : 'ok';
				throw new Error(
					permission === 'denied'
						? 'Notifications are blocked for this site'
						: 'Notifications were not allowed'
				);
			}
			const manager = (await registration()).pushManager;
			let subscription = await manager.getSubscription();
			// Subscribed for another key (Norn's was made anew): that one gets nothing any more.
			if (subscription && !this.device) {
				await subscription.unsubscribe();
				subscription = null;
			}
			subscription ??= await manager.subscribe({
				userVisibleOnly: true,
				applicationServerKey: keyBytes(this.#key)
			});
			const device = await api.addDevice(subscription.toJSON());
			this.device = device;
			this.devices = [...this.devices.filter((d) => d.id !== device.id), device];
		} finally {
			this.busy = false;
		}
	}

	/** Turn them off here: unsubscribe, and Norn forgets the device. */
	async disable(): Promise<void> {
		this.busy = true;
		try {
			const subscription = await (await registration()).pushManager.getSubscription();
			await subscription?.unsubscribe();
			if (this.device) await this.remove(this.device);
			this.device = null;
		} finally {
			this.busy = false;
		}
	}

	async remove(device: PushDevice) {
		await api.removeDevice(device.id);
		this.devices = this.devices.filter((d) => d.id !== device.id);
		if (this.device?.id === device.id) this.device = null;
	}

	async change(device: PushDevice, body: Parameters<typeof api.changeDevice>[1]) {
		const updated = await api.changeDevice(device.id, body);
		this.devices = this.devices.map((d) => (d.id === updated.id ? updated : d));
		if (this.device?.id === updated.id) this.device = updated;
	}
}

export const push = new Push();
