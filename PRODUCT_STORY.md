# Northline Software

The right people get the answer. Everyone else never sees the file.

This is the product story for the presenter. It is not copy for the product UI.

## Problem

A shared workspace answers questions from every research file it can search. An unpublished customer pilot and a team citation standard then look the same. Someone who should only see the standard can be shown a design-partner result that was never released.

## Target user

Northline Software, one tenant, using the product for research documents.

Priya Shah is a Member of Technical Staff. In the product her role is Member. She keeps early research notes.

Daniel Okada is a Senior Member of Technical Staff. In the product his role is Tenant Admin. He publishes research the rest of the tenant is allowed to use.

Samira Holt is a Viewer. She asks questions and should receive only what that role may read.

## Solution

Upload chooses **Visible to**. A member’s file defaults to **Only me**. A tenant admin’s file defaults to **Everyone in this tenant**. Document list, search, and chat apply that same access check before an answer is written. A citation can name only a file the signed-in person can read.

A member who can read a file but does not own it cannot change visibility. The owner can. A Tenant Admin of the same tenant can. Another tenant cannot.

## Core workflow

1. Priya uploads Helios Bank retrieval notes and leaves **Visible to** on **Only me**. The unpublished finding stays in her file: the Helios Bank pilot cut citation misses by 41.7 percent with the reranker northline-rerank-b3.
2. Daniel’s research citation standard is visible to everyone in Northline Software. Members and viewers can read it and ask about it. It names the embedding model northline-embed-v2, and it says a finding is ready for the whole team only with a method section, a measured result, and a named owner.
3. Samira asks which embedding model the standard requires and what three parts a finding needs. The answer cites the research citation standard. The Helios Bank notes are not in her list, her search, or that answer.

## Key differentiator

Access is the product, not a filter on the answer after the fact. The person who cannot see the file does not get it from list, search, or chat. An admin’s broader upload default does not open another person’s **Only me** file. Reading a shared standard does not let a member retarget who else can see it.

## User outcome

Priya keeps the Helios Bank pilot private. Daniel’s citation standard is available to the tenant. Samira gets a cited answer from that standard and never sees the 41.7 percent figure, the customer name, or northline-rerank-b3.

## Demo accounts

From `scripts/seed_demo.py`. The sign-in form does not display these.

- Tenant ID: `northline-software`
- Tenant name on screen after sign-in: Northline Software
- Password for all three: `Northline-demo-1`
- MTS / Member: `priya.shah@northline.demo` (Priya Shah)
- SMTS / Tenant Admin: `daniel.okada@northline.demo` (Daniel Okada)
- Viewer: `samira.holt@northline.demo` (Samira Holt)
