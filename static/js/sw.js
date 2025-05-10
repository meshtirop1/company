self.addEventListener('install', event => {
    event.waitUntil(
        caches.open('hours-tracker-v1').then(cache => {
            return cache.addAll([
                '/',
                '/calendar/',
                '/static/css/base.css',
                '/static/js/base.js',
                '/static/images/icon-192x192.jpeg',
                '/static/images/icon-512x512.jpeg'
            ]);
        })
    );
});

self.addEventListener('fetch', event => {
    event.respondWith(
        caches.match(event.request).then(response => {
            return response || fetch(event.request);
        })
    );
});