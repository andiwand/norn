// Installing Norn as an app. Browsers that can install it (Chrome, Edge, Samsung Internet) fire
// `beforeinstallprompt`; app.html keeps that event in `window.__nornInstall` from the start, as
// it can come before the app runs. Safari has no such event: there it's Share, Add to Home Screen.

interface InstallEvent extends Event {
	prompt(): Promise<void>;
	userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

declare global {
	interface Window {
		__nornInstall?: InstallEvent | null;
	}
}

class Install {
	/** The browser offers to install: `install()` shows its dialog. */
	offered = $state(false);
	/** Running as the installed app. */
	installed = $state(false);

	constructor() {
		if (typeof window === 'undefined') return;
		this.installed =
			matchMedia('(display-mode: standalone)').matches ||
			(navigator as { standalone?: boolean }).standalone === true;
		this.offered = !!window.__nornInstall;
		addEventListener('norn-install', () => (this.offered = !!window.__nornInstall));
		addEventListener('appinstalled', () => {
			this.installed = true;
			this.offered = false;
		});
	}

	/** What stands in the way when the browser doesn't offer it. */
	get hint(): string {
		if (typeof window === 'undefined') return '';
		const ua = navigator.userAgent;
		const touch = navigator.maxTouchPoints > 1;
		if (/iPhone|iPad|iPod/.test(ua) || (touch && /Mac/.test(ua)))
			return 'In Safari, tap Share, then Add to Home Screen.';
		if (/Mac/.test(ua) && /Safari/.test(ua) && !/Chrome|Chromium|Edg|Firefox/.test(ua))
			return 'In Safari, choose File, then Add to Dock.';
		if (/Firefox/.test(ua))
			return "Firefox doesn't install web apps on most systems. Open Norn in Chrome or Edge to install it, or on a phone in Safari or Chrome.";
		if (!isSecureContext)
			return `Browsers install apps only from an HTTPS address, and Norn is open over plain HTTP (${location.host}). Reach it over HTTPS, for example through a reverse proxy or Tailscale Serve, or add a shortcut with the browser menu's Add to Home screen.`;
		return "Use the browser menu's Install app (on a computer also the install icon in the address bar) or Add to Home screen.";
	}

	async install() {
		const event = window.__nornInstall;
		if (!event) return;
		await event.prompt();
		const { outcome } = await event.userChoice;
		window.__nornInstall = null; // a prompt works once
		this.offered = false;
		if (outcome === 'accepted') this.installed = true;
	}
}

export const install = new Install();
