import "./globals.css";

export const metadata = {
  title: "Spotify Reviews — Product Priority Dashboard",
  description: "Auditable product-priority analysis of Spotify reviews.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
