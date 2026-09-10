package com.knowledge.blog.dto;

import lombok.Data;
import java.util.List;

public class RagQueryDto {
    @Data
    public static class Request {
        private String query;
        @com.fasterxml.jackson.annotation.JsonProperty("domain_filter")
        private String domainFilter;
        @com.fasterxml.jackson.annotation.JsonProperty("top_k")
        private Integer topK = 4;
        private List<HistoryMessage> history = List.of();
        @com.fasterxml.jackson.annotation.JsonProperty("retrieval_mode")
        private String retrievalMode = "dense";
        @com.fasterxml.jackson.annotation.JsonProperty("generation_mode")
        private String generationMode = "auto";
        @com.fasterxml.jackson.annotation.JsonProperty("access_scope")
        private AccessScope accessScope;
        @com.fasterxml.jackson.annotation.JsonProperty("allow_web_search")
        private Boolean allowWebSearch = true;
    }

    @Data
    public static class AccessScope {
        @com.fasterxml.jackson.annotation.JsonProperty("user_id")
        private Long userId;
        @com.fasterxml.jackson.annotation.JsonProperty("organization_ids")
        private List<Long> organizationIds = List.of();
        private List<String> roles = List.of();
        @com.fasterxml.jackson.annotation.JsonProperty("is_admin")
        private boolean admin;
    }

    @Data
    public static class HistoryMessage {
        private String role;
        private String content;
    }

    @Data
    public static class Response {
        private String query;
        private String answer;
        private List<SourceItem> sources;
        @com.fasterxml.jackson.annotation.JsonAlias("response_time_ms")
        private Integer responseTimeMs;
        private String intent;
        private String coverage;
        @com.fasterxml.jackson.annotation.JsonAlias("retrieval_mode")
        private String retrievalMode;
        @com.fasterxml.jackson.annotation.JsonAlias("generation_mode")
        private String generationMode;
        @com.fasterxml.jackson.annotation.JsonAlias("selected_citation_count")
        private Integer selectedCitationCount;
        @com.fasterxml.jackson.annotation.JsonAlias("missing_points")
        private List<String> missingPoints;
        private List<TraceStep> trace;
    }

    @Data
    public static class TraceStep {
        private String name;
        private String status;
        @com.fasterxml.jackson.annotation.JsonAlias("latency_ms")
        private Integer latencyMs;
        private String detail;
    }

    @Data
    public static class SourceItem {
        @com.fasterxml.jackson.annotation.JsonAlias("source_type")
        private String sourceType;
        @com.fasterxml.jackson.annotation.JsonAlias("source_id")
        private Long sourceId;
        private String title;
        private String category;
        private String url;
        private String snippet;
        private Double score;
        @com.fasterxml.jackson.annotation.JsonAlias("chunk_index")
        private Integer chunkIndex;
        @com.fasterxml.jackson.annotation.JsonAlias("citation_number")
        private Integer citationNumber;
        private String publisher;
        @com.fasterxml.jackson.annotation.JsonAlias("checked_at")
        private String checkedAt;
    }

    @Data
    public static class IndexReq {
        private String source_type;
        private Long source_id;
        private String title;
        private String content;
        private String category;
        private String tags;
        private String url;
        private String visibility = "PUBLIC";
        private Long owner_id;
        private Long organization_id;
        private List<Long> allowed_user_ids = List.of();
        private List<String> allowed_roles = List.of();
    }

    @Data
    public static class ClassifyRequest {
        private String title;
        private String content;
    }

    @Data
    public static class ClassifyEngineRequest {
        private String title;
        private String content;
        private List<CategoryCandidate> categories;
    }

    @Data
    public static class CategoryCandidate {
        private Long id;
        private String name;
        private String section;
        private String description;
    }

    @Data
    public static class ClassifyResponse {
        @com.fasterxml.jackson.annotation.JsonProperty("category_id")
        private Long categoryId;
        @com.fasterxml.jackson.annotation.JsonProperty("category_name")
        private String categoryName;
        private String section;
        private Double confidence;
    }

    @Data
    public static class DraftRequest {
        private String content;
        private String title;
    }

    @Data
    public static class DraftEngineRequest {
        private String content;
        private String title;
        private List<CategoryCandidate> categories;
    }

    @Data
    public static class DraftResponse {
        private String title;
        private String summary;
        @com.fasterxml.jackson.annotation.JsonProperty("key_points")
        private List<String> keyPoints;
        @com.fasterxml.jackson.annotation.JsonProperty("learning_directions")
        private List<String> learningDirections;
        @com.fasterxml.jackson.annotation.JsonProperty("category_id")
        private Long categoryId;
        @com.fasterxml.jackson.annotation.JsonProperty("category_name")
        private String categoryName;
        private String section;
        private Double confidence;
    }

    @Data
    public static class LearningDirectionRequest {
        @com.fasterxml.jackson.annotation.JsonProperty("checked_direction_ids")
        private List<String> checkedDirectionIds = List.of();
        @com.fasterxml.jackson.annotation.JsonProperty("include_web")
        private Boolean includeWeb = true;
        @com.fasterxml.jackson.annotation.JsonProperty("max_recommendations")
        private Integer maxRecommendations = 4;
    }

    @Data
    public static class LearningDirectionEngineRequest {
        @com.fasterxml.jackson.annotation.JsonProperty("post_id")
        private Long postId;
        private String title;
        private String content;
        private String category;
        @com.fasterxml.jackson.annotation.JsonProperty("existing_directions")
        private List<String> existingDirections = List.of();
        @com.fasterxml.jackson.annotation.JsonProperty("checked_direction_ids")
        private List<String> checkedDirectionIds = List.of();
        @com.fasterxml.jackson.annotation.JsonProperty("include_web")
        private Boolean includeWeb = true;
        @com.fasterxml.jackson.annotation.JsonProperty("max_recommendations")
        private Integer maxRecommendations = 4;
        @com.fasterxml.jackson.annotation.JsonProperty("access_scope")
        private AccessScope accessScope;
    }

    @Data
    public static class LearningDirectionResponse {
        @com.fasterxml.jackson.annotation.JsonAlias("post_id")
        private Long postId;
        private List<LearningRecommendation> recommendations;
        private List<LearningSource> sources;
        @com.fasterxml.jackson.annotation.JsonAlias("retrieval_mode")
        private String retrievalMode;
        @com.fasterxml.jackson.annotation.JsonAlias("web_search_used")
        private Boolean webSearchUsed;
        @com.fasterxml.jackson.annotation.JsonAlias("response_time_ms")
        private Integer responseTimeMs;
        private List<TraceStep> trace;
    }

    @Data
    public static class LearningRecommendation {
        private String id;
        private String topic;
        private String reason;
        @com.fasterxml.jackson.annotation.JsonAlias("evidence_status")
        private String evidenceStatus;
        @com.fasterxml.jackson.annotation.JsonAlias("citation_numbers")
        private List<Integer> citationNumbers;
        private Boolean checked;
    }

    @Data
    public static class LearningSource {
        @com.fasterxml.jackson.annotation.JsonAlias("citation_number")
        private Integer citationNumber;
        @com.fasterxml.jackson.annotation.JsonAlias("source_type")
        private String sourceType;
        @com.fasterxml.jackson.annotation.JsonAlias("source_id")
        private Long sourceId;
        private String title;
        private String url;
        private String publisher;
        private String snippet;
        private Double score;
        @com.fasterxml.jackson.annotation.JsonAlias("checked_at")
        private String checkedAt;
    }
}
