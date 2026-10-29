import { writeFile } from "node:fs/promises";
import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript";
import ts from "typescript";

const SPEC = new URL("../../docs/api/openapi-generated.json", import.meta.url);
const OUTPUT = new URL("../src/shared/api/schema.gen.ts", import.meta.url);

const BLOB = ts.factory.createTypeReferenceNode("Blob");

const ast = await openapiTS(SPEC, {
  enumValues: true,
  // OpenAPI 3.1 marks a file part with `contentMediaType` rather than 3.0's `format: binary`,
  // and openapi-typescript would otherwise type it as `string`.
  transform(schemaObject) {
    return "contentMediaType" in schemaObject ? BLOB : undefined;
  },
});

await writeFile(OUTPUT, COMMENT_HEADER + astToString(ast));
