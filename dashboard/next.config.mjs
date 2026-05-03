/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async headers() {
    return [
      {
        // The dashboard is a private control panel. Even though Basic
        // Auth gates everything except /robots.txt, declare noindex
        // explicitly so a misconfigured deploy doesn't get cached or
        // indexed. Belt + suspenders: HTTP header here, meta tag in
        // layout.js, robots.txt in public/, and middleware Basic Auth.
        source: "/(.*)",
        headers: [
          { key: "X-Robots-Tag", value: "noindex, nofollow, noarchive" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ]
  },
}

export default nextConfig
