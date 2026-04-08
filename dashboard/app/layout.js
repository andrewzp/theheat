export const metadata = {
  title: "@theheat — Control Panel",
  description: "Dashboard for @theheat climate bot",
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
