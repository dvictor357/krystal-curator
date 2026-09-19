"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { signedInHint } from "@/lib/session";

/** Landing CTA: straight to the workspace when a session exists, else to sign-in. */
export function OpenCurator({
  className = "button small",
  children,
}: {
  className?: string;
  children?: React.ReactNode;
}) {
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => setSignedIn(signedInHint()), []);
  return (
    <Link href={signedIn ? "/app" : "/login"} className={className}>
      {signedIn ? "Open workspace" : (children ?? "Open Curator")}
    </Link>
  );
}
