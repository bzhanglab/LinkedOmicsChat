"use client"

import Link from "next/link"
import { ArrowUp, ArrowUpRight, MessageSquare, Eye, BarChart3, Database, Cpu, HelpCircle, Download, Plug } from "lucide-react"

// ── Shared primitives ──────────────────────────────────────────────────────

function H2({ id, icon: Icon, children }: { id: string; icon: React.ElementType; children: React.ReactNode }) {
    return (
        <h2 id={id} className="text-xl font-semibold tracking-tight text-slate-900 mt-14 mb-4 scroll-mt-20 flex items-center gap-2.5">
            <Icon className="w-5 h-5 text-teal-500 flex-shrink-0" />
            {children}
        </h2>
    )
}

function P({ children }: { children: React.ReactNode }) {
    return <p className="text-[15px] text-slate-600 leading-relaxed mb-4">{children}</p>
}

function DefList({ items }: { items: { term: React.ReactNode; text: React.ReactNode }[] }) {
    return (
        <dl className="divide-y divide-slate-100 rounded-xl border border-slate-200/80 bg-white/70">
            {items.map((item, i) => (
                <div key={i} className="px-5 py-3.5 sm:grid sm:grid-cols-[11rem_1fr] sm:gap-6">
                    <dt className="text-sm font-medium text-slate-900">{item.term}</dt>
                    <dd className="mt-1 sm:mt-0 text-sm text-slate-600 leading-relaxed">{item.text}</dd>
                </div>
            ))}
        </dl>
    )
}

function BackToTop() {
    return (
        <div className="mt-4 flex justify-end">
            <a href="#top" className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-teal-700 transition-colors">
                <ArrowUp className="w-3 h-3" />
                Back to top
            </a>
        </div>
    )
}

function ExtLink({ href, children }: { href: string; children: React.ReactNode }) {
    return (
        <a href={href} target="_blank" rel="noopener noreferrer" className="text-teal-700 hover:underline">
            {children}
        </a>
    )
}

// ── Content ───────────────────────────────────────────────────────────────

const SECTIONS = [
    { id: "examples", title: "Asking questions" },
    { id: "example-outputs", title: "Example results" },
    { id: "interpret", title: "Reading the results" },
    { id: "export", title: "Exporting a chat" },
    { id: "mcp", title: "Use from your AI assistant" },
    { id: "data-sources", title: "Data sources" },
    { id: "architecture", title: "How it works" },
    { id: "faq", title: "FAQ" },
]

// All example questions come from the golden test set (backend/examples/langgraph_golden_queries.json).
const EXAMPLES = [
    { term: "Tumor vs. normal", text: "How is EGFR expressed tumor vs normal in LUAD?" },
    { term: "Survival", text: "Show TP53 overall survival in BRCA. · Show TP53 methylation survival in BRCA from TCGA." },
    { term: "Same-gene correlations", text: "Show cis-correlations for MYC." },
    { term: "Treatment response", text: "Which genes best predict paclitaxel response in breast cancer? · Which drugs are patients likely to be resistant to if they have high EGFR expression?" },
    { term: "Drug targets", text: "Is EGFR a validated oncology target? · Which kinases are FDA-approved oncology targets?" },
    { term: "Networks and pathways", text: "Find functional neighbors of TP53 in the FunMap network. · What pathways are enriched in this gene set: EGFR, MET, ERBB2, ALK, RET?" },
    { term: "Literature", text: "Find recent papers on ESR1 and breast cancer survival." },
    { term: "Combined", text: "Is EGFR overexpressed in lung cancer and is it a validated drug target?" },
]

const EXAMPLE_OUTPUTS = [
    {
        title: "Pathway enrichment for a sample gene list",
        shows: "Gene Ontology enrichment plot and table for 15 cell-cycle genes",
        url: "https://chat.linkedomics.org/shared/977d0926-4ce8-411c-8295-e1bb94a295e1",
    },
    {
        title: "Gene biomarkers for checkpoint inhibitor response",
        shows: "Cross-study meta-analysis table, drug-target grid, FunMap network, and tumor-vs-normal expression",
        url: "https://chat.linkedomics.org/shared/addc448b-5e83-48ab-ba3f-749a4233d4eb",
    },
    {
        title: "CDK4 therapeutic potential in breast cancer",
        shows: "Drug-target grid, tumor-vs-normal expression, and clinical trial associations",
        url: "https://chat.linkedomics.org/shared/95167454-c30c-4ac7-b638-17c273d04a3d",
    },
    {
        title: "ESR1 expression and survival in breast cancer",
        shows: "Survival plots across RNA, protein, methylation, and copy number",
        url: "https://chat.linkedomics.org/shared/6c48044d-22e7-462d-b162-9d8c7607796d",
    },
]

const INTERPRETATION = [
    {
        term: "Survival",
        text: "A hazard ratio (HR) above 1 means higher levels of the gene go with shorter overall survival; below 1, with longer survival. CPTAC results compare high- and low-expression groups and are called significant at p < 0.05. In genome-wide TCGA scans thousands of genes are tested, so go by the FDR where it is shown.",
    },
    {
        term: "Tumor vs. normal",
        text: "For each of the 10 CPTAC cohorts, RNA and protein in tumors are compared with adjacent normal tissue. Each cohort gets a direction (higher or lower in tumor), called significant at p < 0.05.",
    },
    {
        term: "Same-gene correlations",
        text: "Correlation across tumors between two measurements of one gene: copy number vs. RNA, methylation vs. RNA, or RNA vs. protein. TCGA uses Spearman correlation by default. A strong positive copy number–RNA correlation suggests a dosage effect, a negative methylation–RNA correlation suggests silencing, and a weak RNA–protein correlation points to regulation after transcription.",
    },
    {
        term: "Treatment response",
        text: "AUROC measures how well expression separates responders from non-responders in a study. Below 0.5, higher expression goes with better response (sensitive); above 0.5, with worse response (resistant). The meta-analysis combines studies: the meta FDR says whether the association holds across them, and the average AUROC gives its direction.",
    },
    {
        term: "FunMap partners",
        text: "The 50 genes closest to your gene in the FunMap network, ranked by random-walk probability. FunMap links are predicted from co-expression across cancers and known protein interactions, so they suggest shared function, not necessarily physical binding.",
    },
    {
        term: "Pathway enrichment",
        text: "Over-representation analysis of Gene Ontology biological processes in WebGestalt. The enrichment ratio is observed ÷ expected genes in a term; judge significance by the FDR. Lists of 10–50 genes work best.",
    },
    {
        term: "Drug-target tiers",
        text: "T1: FDA-approved drug for a cancer indication. T2: FDA-approved for another indication. T3: in clinical trials. T4: preclinical or druggable. T5: cell-surface protein.",
    },
]

const MCP_ADDRESS = "https://chat.linkedomics.org/api/v1/mcp"

const MCP_CLIENTS = [
    {
        term: "Claude (claude.ai and Claude Desktop)",
        text: "Customize › Connectors › Add › Add custom connector. Name it LinkedOmics, paste the address, and leave authentication off. Free plans allow one custom connector; on Team and Enterprise plans an owner adds it under Organization settings › Connectors.",
    },
    {
        term: "ChatGPT",
        text: "In Plugins, select the plus button, then Add custom MCP server. Name it LinkedOmics, paste the address under Connection, and choose no authentication. Workspace settings can block custom servers.",
    },
    {
        term: "Claude Code",
        text: <code className="text-[13px] break-all">claude mcp add --transport http linkedomics {MCP_ADDRESS}</code>,
    },
    {
        term: "Cursor and other MCP clients",
        text: <>Add a remote server with this address (streamable HTTP). In Cursor&rsquo;s <code className="text-[13px]">mcp.json</code>: <code className="text-[13px] break-all">{`{"mcpServers": {"linkedomics": {"url": "${MCP_ADDRESS}"}}}`}</code></>,
    },
]

const EXPORTS = [
    {
        term: "Web page",
        text: "The whole chat with its plots and tables, as an HTML file to open in a browser or share.",
    },
    {
        term: "Python script",
        text: "Repeats each analysis in the chat with the same inputs through the LinkedOmicsChat tool API, so you can check the results or take them further in code. It needs the requests package. The data may have been updated since the chat, so results can differ. Analyses that failed or were blocked in the chat, or whose tools have changed since, are listed as comments instead of being repeated.",
    },
    {
        term: "Methods text",
        text: "A paragraph describing each analysis in the chat (data source, cohort, what was analyzed, and the date it ran) with numbered references to the resources behind it, to adapt for a paper. Check it against the chat before using it.",
    },
]
const DATA_SOURCES = [
    { name: "LinkedOmics", url: "https://www.linkedomics.org", text: "TCGA analyses across 35 cohorts: survival by RNA, methylation, RPPA protein, copy number, or miRNA, and same-gene correlations between methylation, RNA, RPPA, and copy number." },
    { name: "LinkedOmicsKB", url: "https://kb.linkedomics.org", text: "CPTAC proteogenomics for 10 cohorts: tumor-vs-normal RNA and protein, survival, and same-gene correlations." },
    { name: "LinkedOmics Targets", url: "https://targets.linkedomics.org", text: "Drug-target annotations per gene: tier, drugs, cell-line dependency, tumor overexpression, phosphosite activation, driver and antigen evidence." },
    { name: "ClinicalOmicsDB", url: "https://trials.linkedomics.org", text: "Public expression studies from clinical trials with treatment-response labels; used for per-study associations, cross-study meta-analysis, and matching your own gene lists to treatment response." },
    { name: "FunMap", url: "https://funmap.linkedomics.org", text: "Functional network; the app retrieves a gene's top-50 neighborhood." },
    { name: "WebGestalt", url: "https://www.webgestalt.org", text: "Gene Ontology over-representation analysis for gene lists." },
    { name: "PubMed", url: "https://pubmed.ncbi.nlm.nih.gov", text: "Article search and article details." },
    { name: "MyGene.info", url: "https://mygene.info", text: "Converts Ensembl and UniProt IDs to gene symbols." },
]

const FAQS = [
    {
        term: "Do I need an account?",
        text: "No. Without one you can ask 30 questions an hour and run 30 analyses an hour in the Tools view. Signing in raises that to 50 questions and 120 tool runs an hour, saves your chat history, and lets you share chats and export them as HTML.",
    },
    {
        term: "Is my data private?",
        text: "Other users cannot see your chats. Signed-in users' chats are saved to their own account; chats by visitors who aren't signed in are not saved. A chat becomes visible to others only if you create a share link for it. To generate answers, your question and the analysis results are sent to a third-party large language model provider (currently Anthropic). The LinkedOmicsChat team can see usage statistics and short previews of questions in an administrator dashboard, and questions are recorded in server logs for troubleshooting. For visitors who aren't signed in, IP addresses are recorded for rate limiting and usage statistics.",
    },
    {
        term: "Does LinkedOmicsChat use cookies?",
        text: "No. LinkedOmicsChat sets no cookies and uses no tracking or analytics services, so there is no cookie banner. For signed-in users, the browser's local storage keeps the sign-in token and the current chat; for visitors who aren't signed in, a single flag is kept only until the tab is closed.",
    },
    {
        term: "Which cancer types are covered?",
        text: "TCGA analyses support 35 cohort codes, including the combined cohorts COADREAD, GBMLGG, KIPAN, and STES. CPTAC analyses cover 10 cohorts: BRCA, COAD, CCRCC, GBM, HNSCC, LSCC, LUAD, OV, PDAC, and UCEC.",
    },
    {
        term: "Can I analyze my own genes?",
        text: "Yes. Type a few genes into your question, or attach a longer list with the paperclip next to the chat box (a text, CSV, or TSV file, or pasted genes, up to 2,000) and then ask about \"my list\".",
    },
    {
        term: "Can I use these analyses from ChatGPT or Claude?",
        text: "Yes. Add https://chat.linkedomics.org/api/v1/mcp to your assistant as a custom MCP connector; the section on using it from your AI assistant has the steps for Claude, ChatGPT, Claude Code, and Cursor.",
    },
    {
        term: "Can I test my own signature against treatment response?",
        text: "Yes. Attach the list and ask which treatments it predicts response to, or click \"Match to treatments\" next to the list. It is tested against all 67 trial-linked studies in ClinicalOmicsDB, and you can limit it to a cancer type or a treatment, for example immunotherapy in melanoma.",
    },
    {
        term: "Can I run the same analyses for other genes?",
        text: "Yes. Hold the pointer over an answer and click \"Repeat for other genes\" to run its analyses of a single gene again for up to 10 genes, without the language model. The results come back as one table with a row per gene, followed by the plots.",
    },
    {
        term: "Can I repeat an analysis outside the chat?",
        text: "Yes. Signed-in users can export a chat as a Python script that runs the same analyses with the same inputs through the LinkedOmicsChat tool API. The Tools view also runs any single analysis with your own inputs.",
    },
]

// ── Page ──────────────────────────────────────────────────────────────────

export default function DocsPage() {
    return (
        <div className="min-h-screen bg-slate-50">

            {/* Nav */}
            <nav className="sticky top-0 z-20 bg-white/80 backdrop-blur border-b border-slate-100">
                <div className="max-w-3xl mx-auto px-6 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <Link href="/" className="flex items-center gap-2 text-slate-500 hover:text-slate-900 transition-colors text-sm font-medium">
                            <img src="/logo.png" alt="" className="h-5 w-auto" />
                            LinkedOmicsChat
                        </Link>
                        <span className="text-slate-200">/</span>
                        <span className="text-sm font-semibold text-slate-700">Documentation</span>
                    </div>
                    <Link href="/about" className="text-sm text-slate-500 hover:text-slate-900 transition-colors">
                        About
                    </Link>
                </div>
            </nav>

            <div className="max-w-3xl mx-auto px-6 py-12">

                <h1 id="top" className="text-3xl font-bold tracking-tight text-slate-900 mb-5 scroll-mt-20">LinkedOmicsChat documentation</h1>
                <P>
                    LinkedOmicsChat answers questions about cancer genes by running analyses on LinkedOmics and related
                    resources: TCGA and CPTAC multi-omics, clinical-trial expression studies, drug-target annotations, the
                    FunMap network, and WebGestalt enrichment. You ask in plain English; it picks the analyses, runs them
                    against the live services, and returns the plots and tables they produce with a short written summary.
                </P>
                <nav aria-label="On this page" className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                    {SECTIONS.map((sec, i) => (
                        <span key={sec.id} className="flex items-center gap-2">
                            {i > 0 && <span className="text-slate-300">·</span>}
                            <a href={`#${sec.id}`} className="text-teal-700 hover:underline">{sec.title}</a>
                        </span>
                    ))}
                </nav>

                <H2 id="examples" icon={MessageSquare}>Asking questions</H2>
                <P>
                    Name the gene (or genes) and, where it matters, the cancer type. These questions are from the test
                    set the app is checked against, one or two per kind of analysis:
                </P>
                <DefList items={EXAMPLES} />
                <div className="mt-5" />
                <P>
                    You can also analyze your own gene list. A few genes can go straight into the question. For a longer
                    list, click the paperclip next to the chat box and upload a text, CSV, or TSV file or paste the genes.
                    The app finds the gene column, converts Ensembl and UniProt IDs and old gene names to current symbols
                    with MyGene.info, and shows anything it left out, such as a name that could be several genes. Then
                    ask about &ldquo;my list&rdquo;: pathway enrichment uses the whole list, up to 2,000 genes, and
                    per-gene analyses such as survival or drug targets use the first 50. The list stays attached until
                    you remove it or open another chat. To try enrichment on a sample, click &ldquo;Pathway enrichment
                    for a sample gene list&rdquo; on the welcome page.
                </P>
                <P>
                    With a list attached, you can also ask which treatments it predicts response to, or click &ldquo;Match
                    to treatments&rdquo; next to the list; a signature of 5 or more genes typed into the question works
                    too. The app tests the genes against treatment response in every trial-linked study in
                    ClinicalOmicsDB (67 studies across 11 cancer types). In each study it checks whether the genes, as a
                    group, rank toward responders or non-responders, and it sums up how consistently they fall on one
                    side for immune checkpoint inhibitors, chemotherapy, and other targeted therapy. A signature&rsquo;s
                    genes are usually expressed together, which makes a gene-by-gene test look stronger than the
                    patients support, so significance is judged on each study&rsquo;s patients as well as its genes. Many
                    studies are small, so a consistent direction across studies often says more than any single study.
                    These are associations in past studies, not proof that the list predicts response.
                </P>
                <P>
                    For an overview of one gene, ask for a gene report, such as &ldquo;Report on ERBB2&rdquo;, or click
                    the report button next to the chat box. It runs seven analyses at once (tumor vs. normal expression
                    and survival in CPTAC, survival across TCGA cohorts, the drug-target profile, treatment response in
                    trials, FunMap neighbors, and recent PubMed articles) and shows them all with a written overview. A
                    link such as <code className="text-[13px]">chat.linkedomics.org/?q=Report%20on%20ERBB2</code> opens
                    the chat with the request filled in.
                </P>
                <P>
                    To run an answer&rsquo;s analyses again for other genes, hold the pointer over the answer and click
                    &ldquo;Repeat for other genes&rdquo;. Type up to 10 genes, or use an attached list (its first 10
                    genes if it is longer). The analyses of a single gene run again with the new genes, without the
                    language model, so there is no written summary: the answer opens with one table, a row per gene,
                    followed by the usual plots. It takes a few seconds, or up to about half a minute for all of a gene
                    report&rsquo;s analyses. Steps that are not about one gene, such as pathway enrichment or a
                    literature search, are not repeated, and the button appears only on answers that analyzed a single
                    gene.
                </P>
                <P>
                    If a question is too vague to act on, such as a gene with no cancer type or analysis, the app asks
                    which one you mean, usually with clickable options. If it is outside what the tools cover (protein
                    structure, for example), it says so and offers to answer from general knowledge instead. Starting a
                    question with &ldquo;Answer using general knowledge:&rdquo; does that directly; those answers are
                    labeled &ldquo;General knowledge mode&rdquo; and do not come from the data.
                </P>
                <P>
                    To run a single analysis without the language model, open <strong className="font-medium text-slate-800">Tools</strong> in
                    the sidebar. Each of the 27 tools has a form with an example input.
                </P>

                <BackToTop />

                <H2 id="example-outputs" icon={Eye}>Example results</H2>
                <P>
                    These are shared chats from real questions. They open read-only, with the same interactive plots,
                    tables, and networks as the app.
                </P>
                <div className="grid sm:grid-cols-2 gap-3">
                    {EXAMPLE_OUTPUTS.map((ex) => (
                        <a
                            key={ex.url}
                            href={ex.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="group rounded-xl border border-slate-200/80 bg-white/70 p-4 hover:border-teal-300 hover:bg-white transition-colors"
                        >
                            <p className="text-sm font-medium text-slate-900 mb-1 flex items-center gap-1.5">
                                {ex.title}
                                <ArrowUpRight className="w-3.5 h-3.5 text-slate-400 group-hover:text-teal-600" />
                            </p>
                            <p className="text-sm text-slate-500 leading-relaxed">{ex.shows}</p>
                        </a>
                    ))}
                </div>

                <BackToTop />

                <H2 id="interpret" icon={BarChart3}>Reading the results</H2>
                <P>
                    The numbers, tables, and plots come straight from the analysis output, and each section links to its
                    source. The written summary is generated by the language model from those same results, so check
                    anything important against the tables. All results are associations in public patient cohorts, not
                    evidence of cause and effect.
                </P>
                <DefList items={INTERPRETATION} />
                <div className="mt-5" />
                <P>
                    Under each written summary, the number check shows how its numbers compare with the analysis
                    output. A number with a dotted underline was found there; hold the pointer over it to see which
                    result it came from. A highlighted number is in no tool result, so check it before you use it.
                    Counts the summary works out itself, such as &ldquo;9 of 50 genes&rdquo;, and thresholds such as
                    p &lt; 0.05 are not checked. &ldquo;Found&rdquo; means a value that rounds to the number is in the
                    output. It does not confirm that the sentence ties it to the right gene, cohort, or study, and in
                    large results a short number can match an unrelated value by chance; the hover shows which result
                    the value came from.
                </P>

                <BackToTop />

                <H2 id="export" icon={Download}>Exporting a chat</H2>
                <P>
                    Signed-in users can export a chat with the Export button at the top right of the chat, in three formats:
                </P>
                <DefList items={EXPORTS} />

                <BackToTop />

                <H2 id="mcp" icon={Plug}>Use from your AI assistant</H2>
                <P>
                    The analyses are also open to other AI assistants and agents through the Model Context Protocol
                    (MCP). Add this address to the assistant you already use and ask your questions there; it chooses
                    the analyses and writes the answer with its own model.
                </P>
                <p className="my-3 rounded-md bg-muted px-3 py-2 font-mono text-[13px] break-all">{MCP_ADDRESS}</p>
                <DefList items={MCP_CLIENTS} />
                <P>
                    It offers 25 of the app&rsquo;s 27 tools: all except the two PubMed tools, since assistants have
                    their own literature search. Results come shortened, as the chat&rsquo;s own agent sees them; the
                    Tools view shows the full output. The chat&rsquo;s plots and its checks, such as blocking analyses
                    of genes nobody asked about and the number check, stay in the chat: an outside assistant gets the
                    results with their sources, and checking its answer is up to it.
                </P>
                <P>
                    Each address can make 100 tool calls an hour, and calls to the slowest services run a few at a
                    time, so heavy use waits its turn; for more, use the Feedback link. The service records each
                    call&rsquo;s tool, time, and duration with a coded ID for the address, not the address itself or
                    what was asked. Please cite LinkedOmicsChat and the resources each result names (About › Cite).
                </P>

                <BackToTop />

                <H2 id="data-sources" icon={Database}>Data sources</H2>
                <P>
                    LinkedOmicsChat keeps no copy of these datasets; each analysis queries the service when you ask. The
                    exceptions are the drug-target index, which is cached for a day, and ClinicalOmicsDB&rsquo;s per-study
                    gene rankings for treatment response matching, which are refreshed weekly.
                </P>
                <DefList items={DATA_SOURCES.map((s) => ({ term: <ExtLink href={s.url}>{s.name}</ExtLink>, text: s.text }))} />

                <BackToTop />

                <H2 id="architecture" icon={Cpu}>How it works</H2>
                <P>
                    The chat runs a LangGraph agent on Claude Haiku 5.5 (Anthropic API) with 27 tools served by three
                    MCP servers: 23 analyses on the LinkedOmics family of resources, FunMap, and WebGestalt; one gene ID
                    converter; and two PubMed tools. Before the model sees a question, a keyword router decides which
                    group of tools is relevant and only those are offered, and any Ensembl or UniProt IDs are converted
                    to gene symbols.
                </P>
                <P>
                    The model then calls tools, and can chain them: for &ldquo;find TP53&rsquo;s FunMap neighbors and run
                    enrichment&rdquo;, it passes the neighbors from the first call to the second. Every call is checked
                    against the genes in your question plus any genes returned earlier in the same answer, and a call on
                    some other gene is blocked, so the model cannot quietly swap in a gene you did not ask about. Each
                    call starts its own tool-server process and queries the live service; answers take from a few seconds
                    to under a minute, depending on how many analyses they need.
                </P>
                <P>
                    The server builds the plots and tables from the tool output: static plots with matplotlib, and
                    interactive tables, drug-target grids, and network views in the browser. The written summary comes
                    from the model, working from the same results. After the summary is written, the server looks for each
                    of its numbers in the tool output, allowing for rounding, which is what the number check shows. A gene
                    report skips the model&rsquo;s choice of tools: its seven analyses run at once, and the model writes
                    only the summary. A repeat for other genes skips the model altogether: it reruns an earlier
                    answer&rsquo;s analyses with the new genes and builds the table from the results. Treatment response
                    matching reads every ClinicalOmicsDB study&rsquo;s full gene ranking from a copy on the server,
                    refreshed weekly. The backend is
                    FastAPI with LangGraph and FastMCP, and the
                    frontend is Next.js; the source is on{" "}
                    <ExtLink href="https://github.com/bzhanglab/LinkedOmicsChat">GitHub</ExtLink>.
                </P>

                <BackToTop />

                <H2 id="faq" icon={HelpCircle}>FAQ</H2>
                <DefList items={FAQS} />
                <BackToTop />

                <div className="mt-14 pt-8 border-t border-slate-200 flex flex-wrap items-center justify-between gap-4">
                    <div className="flex gap-3">
                        <Link
                            href="/"
                            className="bg-teal-600 hover:bg-teal-700 text-white font-semibold px-5 py-2 rounded-lg text-sm transition-colors inline-flex items-center gap-1.5"
                        >
                            Start asking questions
                            <ArrowUpRight className="w-4 h-4" />
                        </Link>
                        <Link
                            href="/register"
                            className="border border-slate-200 hover:border-slate-300 bg-white/80 hover:bg-white text-slate-700 font-semibold px-5 py-2 rounded-lg text-sm transition-colors"
                        >
                            Create free account
                        </Link>
                    </div>
                    <p className="text-xs text-slate-400">
                        Zhang Lab · Free to use · Source code under the{" "}
                        <a href="https://github.com/bzhanglab/LinkedOmicsChat/blob/main/LICENSE" target="_blank" rel="noopener noreferrer" className="underline hover:text-slate-600 transition-colors">MIT License</a>
                    </p>
                </div>

            </div>
        </div>
    )
}
