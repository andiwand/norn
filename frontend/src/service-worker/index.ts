// The service worker: it shows Norn's notifications (web push) and opens the page they are
// about. It caches nothing: Norn is live video, an offline copy would only show old things.
// Having one also lets Android install Norn as an app.

const sw = self as unknown as ServiceWorkerGlobalScope;

interface Message {
	title?: string;
	body?: string;
	tag?: string;
	url?: string;
	image?: string | null;
	time?: number;
}

sw.addEventListener('install', () => sw.skipWaiting());
sw.addEventListener('activate', (event) => event.waitUntil(sw.clients.claim()));

sw.addEventListener('push', (event) => {
	let message: Message = {};
	try {
		message = event.data?.json() ?? {};
	} catch {
		message = { body: event.data?.text() };
	}
	const options: NotificationOptions & { image?: string; renotify?: boolean; timestamp?: number } =
		{
			body: message.body ?? '',
			tag: message.tag,
			renotify: !!message.tag, // a new detection on the same camera alerts again
			icon: '/icon-192.png',
			// The picture: Android shows it large; iOS shows none.
			image: message.image ?? undefined,
			timestamp: message.time,
			data: { url: message.url ?? '/' }
		};
	event.waitUntil(sw.registration.showNotification(message.title ?? 'Norn', options));
});

// A tap opens what it is about: in a window of Norn that is open already, else a new one.
sw.addEventListener('notificationclick', (event) => {
	event.notification.close();
	const url = new URL(event.notification.data?.url ?? '/', sw.location.origin).href;
	event.waitUntil(
		(async () => {
			const windows = await sw.clients.matchAll({ type: 'window', includeUncontrolled: true });
			for (const client of windows) {
				try {
					const focused = await client.focus();
					await focused.navigate(url);
					return;
				} catch {
					// not ours to steer: open a new one
				}
			}
			await sw.clients.openWindow(url);
		})()
	);
});
