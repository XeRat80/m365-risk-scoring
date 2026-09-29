import {RiskCommand} from "@/components/risk-command";

export default async function UserPage({params}: {params: Promise<{userId: string}>}) {
  const {userId} = await params;
  return <RiskCommand view="user" userId={userId}/>;
}
