import "../../../../app/dashboard.css"

export const metadata = { title: "Operator media journey (invented)", robots: { index: false, follow: false } }

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
