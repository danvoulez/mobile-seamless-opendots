// Gives "Add to Dock" (Safari) and "Install" (Chrome) the Open Dots name and
// icon. The icons are the iPhone app's, served by the same Open Dots server.

// Written once at build time: the Mac page is exported as plain files.
export const dynamic = 'force-static';

export default function manifest() {
  return {
    name: 'Open Dots',
    short_name: 'Open Dots',
    description: 'Your Open Dots conversations, on this computer.',
    start_url: '/',
    scope: '/',
    display: 'standalone',
    background_color: '#09090b',
    theme_color: '#09090b',
    icons: [
      { src: '/m/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
      { src: '/m/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
    ],
  };
}
