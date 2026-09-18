import { notFound } from "next/navigation";
import { Workspace } from "@/components/workspace";
export const metadata = { title: "Workspace" };
export default async function App({
  params,
}: {
  params: Promise<{ section?: string[] }>;
}) {
  const { section } = await params;
  const page = section?.[0] || "screener";
  if (
    (section?.length || 0) > 1 ||
    !["screener", "watchlist", "positions", "leaderboard", "settings"].includes(
      page,
    )
  )
    notFound();
  return <Workspace page={page} />;
}
