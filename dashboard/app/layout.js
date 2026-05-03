export const metadata = {
  title: "@theheat — Control Panel",
  description: "Dashboard for @theheat climate bot",
  // Internal control panel — no public discovery. Mirrored by
  // X-Robots-Tag header in next.config.mjs and robots.txt in public/.
  robots: {
    index: false,
    follow: false,
    nocache: true,
    googleBot: {
      index: false,
      follow: false,
      noimageindex: true,
    },
  },
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
