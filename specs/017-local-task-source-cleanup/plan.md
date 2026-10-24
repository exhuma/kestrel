# Implementation Plan: Local task source cleanup

**Branch**: `master` | **Date**: 2026-09-10 | **Spec**: [spec.md](spec.md)

## Summary

Replace the fixture source contract with local tasks, use one shared development
runtime, and remove the obsolete isolated configuration.

## Constitution Check

The change retains backend-owned source behavior, keeps local tasks private for
reruns, adds focused backend and frontend tests, and introduces no dependency.
