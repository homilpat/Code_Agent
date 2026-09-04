package com.knowledge.blog.controller;

import com.knowledge.blog.dto.RagQueryDto;
import com.knowledge.blog.service.RagService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@RequestMapping("/api/rag")
@RequiredArgsConstructor
public class RagController {

    private final RagService ragService;

    @PostMapping("/query")
    public ResponseEntity<RagQueryDto.Response> queryKnowledge(@RequestBody RagQueryDto.Request request) {
        return ResponseEntity.ok(ragService.searchAndAnswer(request));
    }

    @GetMapping("/evaluation/latest")
    public ResponseEntity<Map<String, Object>> latestEvaluation() {
        return ResponseEntity.ok(ragService.latestEvaluation());
    }

    @PostMapping("/classify")
    public ResponseEntity<RagQueryDto.ClassifyResponse> classifyPost(@RequestBody RagQueryDto.ClassifyRequest request) {
        return ResponseEntity.ok(ragService.classifyPost(request));
    }

    @PostMapping("/draft")
    public ResponseEntity<RagQueryDto.DraftResponse> generatePostDraft(@RequestBody RagQueryDto.DraftRequest request) {
        return ResponseEntity.ok(ragService.generatePostDraft(request));
    }
}
