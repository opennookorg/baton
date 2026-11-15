import { Bot, Braces, Check, Copy, ExternalLink, Globe, HardDrive, MessagesSquare, MousePointer2, Plug, ShieldCheck, SquareTerminal, TerminalSquare, Waypoints, type LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

type Transport = "local" | "remote";
type Place = { dir: string; url: string };
type Snippet = { title: string; code: (place: Place) => string };
type Setup = { snippets: Snippet[]; steps?: string[] };

export const CLIENT_IDS = ["claude-code", "chatgpt", "codex", "cursor", "opencode", "hermes", "openclaw", "other"] as const;
export type ClientId = (typeof CLIENT_IDS)[number];

type Client = {
  id: ClientId;
  name: string;
  maker: string;
  icon: LucideIcon;
  docs?: string;
  local?: Setup;
  remote: Setup;
  verify: { command?: string; text: string };
};

const launch = ({ dir }: Place) => ["uv", "--directory", dir, "run", "python", "-m", "agent.mcp_server"];
const shellLaunch = (place: Place) => launch(place).map((part) => (/[\s'"]/.test(part) ? `"${part}"` : part)).join(" ");
const jsonArgs = (place: Place) => JSON.stringify(launch(place).slice(1));
const mcpServersJson = (entry: object) => JSON.stringify({ mcpServers: { baton: entry } }, null, 2);

const CLIENTS: Client[] = [
  {
    id: "claude-code",
    name: "Claude Code",
    maker: "Anthropic",
    icon: SquareTerminal,
    docs: "https://code.claude.com/docs/en/mcp",
    local: {
      snippets: [{ title: "Terminal", code: (place) => `claude mcp add --transport stdio --scope user baton -- ${shellLaunch(place)}` }],
      steps: ["Inside the Baton repo you can skip this: .mcp.json already registers the server, so approve it when Claude Code asks."],
    },
    remote: { snippets: [{ title: "Terminal", code: ({ url }) => `claude mcp add --transport http --scope user baton ${url}` }] },
    verify: { command: "claude mcp list", text: "baton shows as connected, and /mcp inside a session lists its tools." },
  },
  {
    id: "chatgpt",
    name: "ChatGPT",
    maker: "OpenAI",
    icon: MessagesSquare,
    docs: "https://developers.openai.com/api/docs/guides/developer-mode",
    remote: {
      steps: [
        "Start the remote server below and copy its public URL.",
        "Open chatgpt.com/plugins, press the plus button and choose Add custom MCP server.",
        "Name it Baton, paste the server URL and set Authentication to No authentication.",
        "Tick I understand and want to continue, then Create as a plugin and install it.",
        "In a chat, type @Baton and paste an issue.",
      ],
      snippets: [{ title: "Server URL", code: ({ url }) => url }],
    },
    verify: { text: "Ask it to route an issue. ChatGPT should call route_issue and quote the teams it returns." },
  },
  {
    id: "codex",
    name: "Codex",
    maker: "OpenAI",
    icon: TerminalSquare,
    docs: "https://learn.chatgpt.com/docs/extend/mcp?surface=cli",
    local: {
      snippets: [
        { title: "Terminal", code: (place) => `codex mcp add baton -- ${shellLaunch(place)}` },
        { title: "~/.codex/config.toml", code: (place) => `[mcp_servers.baton]\ncommand = "uv"\nargs = ${jsonArgs(place).replaceAll(",", ", ")}` },
      ],
    },
    remote: {
      snippets: [
        { title: "Terminal", code: ({ url }) => `codex mcp add baton --url ${url}` },
        { title: "~/.codex/config.toml", code: ({ url }) => `[mcp_servers.baton]\nurl = "${url}"` },
      ],
    },
    verify: { command: "codex mcp list", text: "baton is listed, and /mcp inside the TUI shows its tools." },
  },
  {
    id: "cursor",
    name: "Cursor",
    maker: "Anysphere",
    icon: MousePointer2,
    docs: "https://cursor.com/docs/context/mcp",
    local: { snippets: [{ title: "~/.cursor/mcp.json", code: (place) => mcpServersJson({ type: "stdio", command: "uv", args: launch(place).slice(1) }) }] },
    remote: { snippets: [{ title: "~/.cursor/mcp.json", code: ({ url }) => mcpServersJson({ url }) }] },
    verify: { text: "baton appears enabled in Cursor's MCP settings. Its logs are under Output, MCP Logs." },
  },
  {
    id: "opencode",
    name: "OpenCode",
    maker: "SST",
    icon: Braces,
    docs: "https://opencode.ai/docs/mcp-servers/",
    local: { snippets: [{ title: "opencode.jsonc", code: (place) => JSON.stringify({ $schema: "https://opencode.ai/config.json", mcp: { servers: { baton: { type: "local", command: launch(place) } } } }, null, 2) }] },
    remote: { snippets: [{ title: "opencode.jsonc", code: ({ url }) => JSON.stringify({ $schema: "https://opencode.ai/config.json", mcp: { servers: { baton: { type: "remote", url, oauth: false } } } }, null, 2) }] },
    verify: { command: "opencode mcp list", text: "baton is listed as connected." },
  },
  {
    id: "hermes",
    name: "Hermes Agent",
    maker: "Nous Research",
    icon: Bot,
    docs: "https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp",
    local: { snippets: [{ title: "~/.hermes/config.yaml", code: (place) => `mcp_servers:\n  baton:\n    command: "uv"\n    args: ${jsonArgs(place).replaceAll(",", ", ")}` }] },
    remote: { snippets: [{ title: "~/.hermes/config.yaml", code: ({ url }) => `mcp_servers:\n  baton:\n    url: "${url}"` }] },
    verify: { command: "hermes mcp test baton", text: "Run /reload-mcp in an open session. Tools show up as mcp_baton_route_issue and so on." },
  },
  {
    id: "openclaw",
    name: "OpenClaw",
    maker: "Open source",
    icon: Waypoints,
    docs: "https://docs.openclaw.ai/tools/mcp.md",
    local: { snippets: [{ title: "OpenClaw config (JSON5)", code: (place) => `{\n  mcp: {\n    servers: {\n      baton: { command: "uv", args: ${jsonArgs(place).replaceAll(",", ", ")} },\n    },\n  },\n}` }] },
    remote: { snippets: [{ title: "Terminal", code: ({ url }) => `openclaw mcp add baton --url ${url} --transport streamable-http` }] },
    verify: { command: "openclaw mcp probe baton", text: "The probe lists the baton tools." },
  },
  {
    id: "other",
    name: "Any MCP client",
    maker: "Claude Desktop, Windsurf and more",
    icon: Plug,
    local: { snippets: [{ title: "mcpServers entry", code: (place) => mcpServersJson({ command: "uv", args: launch(place).slice(1) }) }] },
    remote: { snippets: [{ title: "mcpServers entry", code: ({ url }) => mcpServersJson({ type: "http", url }) }] },
    verify: { text: "Most clients use this mcpServers shape. Ask the client to list its tools and look for route_issue." },
  },
];

const TOOLS = [
  { name: "route_issue", about: "Ranks the teams that own an issue, with the graph path behind each one and a confidence.", writes: false },
  { name: "similar_past_issues", about: "Past issues that share entities with this one, and who fixed them.", writes: false },
  { name: "reporter_history", about: "Which teams a reporter's earlier issues went to.", writes: false },
  { name: "team_profile", about: "The components, files and labels a team owns, strongest first.", writes: false },
  { name: "record_outcome", about: "Feeds a human-confirmed owner back into the graph so it learns.", writes: true },
];

const DEFAULT_PLACE: Place = { dir: "/path/to/baton", url: "https://your-tunnel.trycloudflare.com/mcp" };

function storedPlace(): Place {
  try {
    return { ...DEFAULT_PLACE, ...JSON.parse(localStorage.getItem("baton-connect") ?? "{}") };
  } catch {
    return DEFAULT_PLACE;
  }
}

function hostOf(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return "your-tunnel.trycloudflare.com";
  }
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);
  return (
    <Button
      variant="ghost"
      size="icon-xs"
      aria-label={copied ? "Copied" : `Copy ${label}`}
      title="Copy"
      onClick={() => navigator.clipboard.writeText(text).then(() => setCopied(true), () => setCopied(false))}
    >
      {copied ? <Check className="text-brand" /> : <Copy />}
    </Button>
  );
}

function CodeBlock({ title, code }: { title: string; code: string }) {
  return (
    <figure className="overflow-hidden rounded-lg border bg-muted/40">
      <figcaption className="flex items-center justify-between border-b py-1 pr-1 pl-3 font-mono text-xs text-muted-foreground">
        {title}
        <CopyButton text={code} label={title} />
      </figcaption>
      <pre className="overflow-x-auto p-3 font-mono text-[13px] leading-relaxed">
        <code className="bg-transparent p-0 text-[1em]">{code}</code>
      </pre>
    </figure>
  );
}

function ClientSetup({ client, place }: { client: Client; place: Place }) {
  const [chosen, setChosen] = useState<Transport>("local");
  const transport: Transport = client.local ? chosen : "remote";
  const setup = transport === "local" && client.local ? client.local : client.remote;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <client.icon className="size-4 text-muted-foreground" aria-hidden="true" />
          Connect {client.name}
        </CardTitle>
        <CardDescription>
          {transport === "local" ? "Runs the server on this machine over stdio, with all five tools." : "Reaches the server over HTTPS. Read-only: record_outcome is not exposed."}
        </CardDescription>
        {client.docs && (
          <CardAction>
            <Button variant="ghost" size="sm" asChild>
              <a href={client.docs} target="_blank" rel="noreferrer">
                Docs <ExternalLink />
              </a>
            </Button>
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {client.local ? (
          <ToggleGroup type="single" variant="outline" size="sm" value={transport} onValueChange={(value) => value && setChosen(value as Transport)} aria-label="Transport">
            <ToggleGroupItem value="local">
              <HardDrive /> Local
            </ToggleGroupItem>
            <ToggleGroupItem value="remote">
              <Globe /> Remote
            </ToggleGroupItem>
          </ToggleGroup>
        ) : (
          <Badge variant="secondary">
            <Globe /> Remote only
          </Badge>
        )}
        {setup.steps && (
          <ol className="list-decimal space-y-1 pl-5 text-muted-foreground marker:text-muted-foreground/70">
            {setup.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        )}
        {setup.snippets.map((snippet) => (
          <CodeBlock key={snippet.title} title={snippet.title} code={snippet.code(place)} />
        ))}
        <div className="rounded-lg border border-dashed p-3">
          <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium">
            <ShieldCheck className="size-3.5 text-brand" aria-hidden="true" />
            Check it worked
          </p>
          {client.verify.command && <CodeBlock title="Terminal" code={client.verify.command} />}
          <p className="mt-1.5 text-muted-foreground">{client.verify.text}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function ConnectPage({ client, onClient }: { client: ClientId; onClient: (client: ClientId) => void }) {
  const [place, setPlace] = useState<Place>(storedPlace);
  const update = (patch: Partial<Place>) =>
    setPlace((current) => {
      const next = { ...current, ...patch };
      try {
        localStorage.setItem("baton-connect", JSON.stringify(next));
      } catch {}
      return next;
    });
  const host = hostOf(place.url);

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="min-w-0 space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Where Baton runs</CardTitle>
            <CardDescription>Every snippet on this page fills in from these two values. They stay in this browser.</CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="baton-dir">Baton checkout</Label>
              <Input id="baton-dir" value={place.dir} spellCheck={false} className="font-mono" onChange={(event) => update({ dir: event.target.value })} />
              <p className="text-xs text-muted-foreground">Local clients launch the server from here with uv.</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="baton-url">Public MCP URL</Label>
              <Input id="baton-url" value={place.url} spellCheck={false} className="font-mono" onChange={(event) => update({ url: event.target.value })} />
              <p className="text-xs text-muted-foreground">For ChatGPT and other remote clients. Ends in /mcp.</p>
            </div>
          </CardContent>
        </Card>

        <Tabs value={client} onValueChange={(value) => onClient(value as ClientId)} className="gap-4">
          <TabsList aria-label="MCP client" className="grid w-full grid-cols-2 gap-2 bg-transparent p-0 group-data-horizontal/tabs:h-auto sm:grid-cols-4">
            {CLIENTS.map((option) => (
              <TabsTrigger
                key={option.id}
                value={option.id}
                className="h-auto flex-col items-start gap-0.5 rounded-lg border-border bg-card px-3 py-2.5 text-left whitespace-normal shadow-xs hover:bg-muted/50 data-active:border-brand data-active:bg-brand-soft dark:data-active:border-brand dark:data-active:bg-brand-soft"
              >
                <span className="flex items-center gap-1.5 text-foreground">
                  <option.icon className="size-4 text-muted-foreground" aria-hidden="true" />
                  {option.name}
                </span>
                <span className="text-xs font-normal text-muted-foreground">{option.maker}</span>
              </TabsTrigger>
            ))}
          </TabsList>
          {CLIENTS.map((option) => (
            <TabsContent key={option.id} value={option.id}>
              <ClientSetup client={option} place={place} />
            </TabsContent>
          ))}
        </Tabs>
      </div>

      <div className="min-w-0 space-y-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Globe className="size-4 text-muted-foreground" aria-hidden="true" />
              Run the remote server
            </CardTitle>
            <CardDescription>Remote clients need an HTTPS URL. A free Cloudflare quick tunnel gives you one, no account needed.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <CodeBlock title="1. Open a tunnel to port 8001" code="cloudflared tunnel --url http://127.0.0.1:8001" />
            <CodeBlock title="2. Start Baton with the tunnel host" code={`cd ${place.dir}\nuv run python -m agent.mcp_server --http --allow-host ${host}`} />
            <p className="text-muted-foreground">
              Paste the tunnel's address into <span className="font-medium text-foreground">Public MCP URL</span> with <code>/mcp</code> on the end. The server answers only to the hosts you allow, and never exposes <code>record_outcome</code>.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Tools</CardTitle>
            <CardDescription>What an agent can call once connected.</CardDescription>
          </CardHeader>
          <CardContent className="px-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">Tool</TableHead>
                  <TableHead className="pr-4 text-right">Access</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {TOOLS.map((tool) => (
                  <TableRow key={tool.name}>
                    <TableCell className="pl-4 whitespace-normal">
                      <div className="font-mono text-[13px]">{tool.name}</div>
                      <div className="text-xs text-muted-foreground">{tool.about}</div>
                    </TableCell>
                    <TableCell className="pr-4 text-right align-top">
                      <Badge variant={tool.writes ? "outline" : "secondary"}>{tool.writes ? "Local only" : "Read"}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
